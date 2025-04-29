import pandas as pd
import ast
import logging
import re
from sqlalchemy import create_engine, text
from database.db import engine

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('data_update.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

def clean_clid(clid):
    """Извлечение только цифр из строки clid."""
    if pd.notnull(clid) and isinstance(clid, str):
        # Извлекаем только цифры
        digits = re.sub(r'\D', '', clid)
        return digits if digits else None
    return clid

def evaluate_lists(col):
    """Преобразование строкового представления списка в Python-список."""
    if pd.notnull(col) and isinstance(col, str) and col.startswith('[') and col.endswith(']'):
        try:
            return ast.literal_eval(col)
        except (SyntaxError, ValueError) as e:
            logger.warning(f"Ошибка преобразования списка в столбце: {col}, ошибка: {str(e)}")
            return col
    return col

def prepare_sql_array(lst):
    """Преобразование списка в строку для хранения в TEXT поле."""
    if isinstance(lst, list):
        return str(lst)
    return None if lst is None else lst

def load_csv_to_temp_table(file_path: str, temp_table_name: str) -> pd.DataFrame:
    """Загрузка данных из CSV во временную таблицу."""
    try:
        df = pd.read_csv(file_path)
        logger.info(f"Загружен CSV-файл: {file_path}, записей: {len(df)}")

        # Обрабатываем clid: извлекаем только цифры
        if 'clid' in df.columns:
            df['clid'] = df['clid'].apply(clean_clid)

        # Проверяем дубликаты по ключевым столбцам
        table_name = temp_table_name.replace('_temp', '')
        if table_name in ['employees', 'placements', 'positions', 'subdivisions']:
            duplicates = df[df.duplicated(subset=['id'], keep=False)]
            if not duplicates.empty:
                logger.warning(f"Найдены дубликаты в {file_path}: {len(duplicates)} записей")
                logger.warning(f"Дубликаты:\n{duplicates}")
                df = df.drop_duplicates(subset=['id'], keep='last')
                logger.info(f"После удаления дубликатов осталось записей: {len(df)}")
        elif table_name == 'presence_report':
            duplicates = df[df.duplicated(subset=['employee_id', 'date'], keep=False)]
            if not duplicates.empty:
                logger.warning(f"Найдены дубликаты в {file_path}: {len(duplicates)} записей")
                logger.warning(f"Дубликаты:\n{duplicates}")
                df = df.drop_duplicates(subset=['employee_id', 'date'], keep='last')
                logger.info(f"После удаления дубликатов осталось записей: {len(df)}")

        # Список столбцов, которые содержат массивы (хранятся как TEXT в базе)
        list_columns = {
            'employees': ['placements', 'sites', 'subdivisions', 'positions', 'identification_photos'],
            'placements': ['ips', 'mac_addresses', 'managers'],
            'positions': ['managers', 'subdivisions'],
            'subdivisions': ['managers', 'placements']
        }

        # Преобразуем строковые списки в Python-списки и затем обратно в строки
        if table_name in list_columns:
            for col in list_columns[table_name]:
                if col in df.columns:
                    df[col] = df[col].apply(evaluate_lists)
                    df[col] = df[col].apply(prepare_sql_array)

        # Заменяем NaN на None для корректной вставки в базу
        df = df.where(pd.notnull(df), None)

        # Загружаем данные во временную таблицу
        df.to_sql(temp_table_name, engine, if_exists='replace', index=False)
        logger.info(f"Данные загружены во временную таблицу {temp_table_name}, записей: {len(df)}")
        return df
    except Exception as e:
        logger.error(f"Ошибка загрузки CSV {file_path} во временную таблицу {temp_table_name}: {str(e)}")
        raise

def clear_and_replace_table(connection, table_name: str, temp_table_name: str):
    """Очистка таблицы и вставка новых данных из временной таблицы."""
    try:
        # Очищаем зависимые таблицы перед удалением записей из основной таблицы
        if table_name == "employees":
            # Удаляем связанные записи из presence_report
            connection.execute(text("DELETE FROM presence_report WHERE employee_id IN (SELECT id FROM employees);"))
            logger.info("Удалены связанные записи из таблицы presence_report")

            # Удаляем записи из user_settings, ссылающиеся на текущие employee_id
            connection.execute(text("DELETE FROM user_settings WHERE employee_id IN (SELECT id FROM employees);"))
            logger.info("Удалены записи из user_settings, ссылающиеся на текущие employee_id")

            # Удаляем записи из notifications, ссылающиеся на несуществующие telegram_id
            connection.execute(text("""
                DELETE FROM notifications
                WHERE telegram_id NOT IN (SELECT telegram_id FROM user_settings);
            """))
            logger.info("Удалены записи из notifications, ссылающиеся на несуществующие telegram_id")

        # Очищаем основную таблицу
        connection.execute(text(f"DELETE FROM {table_name};"))
        logger.info(f"Таблица {table_name} полностью очищена")

        # Вставляем новые данные из временной таблицы
        if table_name == "employees":
            query = f"""
                INSERT INTO employees (
                    id, user_id, company_id, timezone_id, telegram_id,
                    presence_close_rule, phone, identification_photos,
                    identification_photos_count, preferred_photo, email,
                    positions, avatar, avatar_big, placements, first_name,
                    last_name, snils, clid, sites, subdivisions
                )
                SELECT
                    id::BIGINT,
                    user_id::DOUBLE PRECISION,
                    company_id::BIGINT,
                    timezone_id::BIGINT,
                    telegram_id::DOUBLE PRECISION,
                    presence_close_rule::DOUBLE PRECISION,
                    phone::DOUBLE PRECISION,
                    identification_photos::TEXT,
                    identification_photos_count::DOUBLE PRECISION,
                    preferred_photo::DOUBLE PRECISION,
                    email::TEXT,
                    positions::TEXT,
                    avatar::TEXT,
                    avatar_big::TEXT,
                    placements::TEXT,
                    first_name::TEXT,
                    last_name::TEXT,
                    snils::TEXT,
                    clid::TEXT,
                    sites::TEXT,
                    subdivisions::TEXT
                FROM {temp_table_name};
            """
            # Выполняем вставку новых данных в employees
            connection.execute(text(query))
            logger.info(f"Новые данные вставлены в таблицу {table_name}")

            # Добавляем новых сотрудников в user_settings (если их telegram_id ещё нет)
            connection.execute(text("""
                INSERT INTO user_settings (
                    telegram_id, employee_id, subscribed, 
                    arrival_notification_times, departure_notification_times
                )
                SELECT DISTINCT
                    t.telegram_id::BIGINT,
                    t.id::BIGINT,
                    TRUE,
                    '[]',
                    '[]'
                FROM {temp_table_name} t
                WHERE t.telegram_id IS NOT NULL
                AND t.telegram_id::BIGINT NOT IN (SELECT telegram_id FROM user_settings)
                ON CONFLICT (telegram_id) DO NOTHING;
            """.format(temp_table_name=temp_table_name)))
            logger.info("Добавлены новые сотрудники в user_settings")

        elif table_name == "placements":
            query = f"""
                INSERT INTO placements (
                    id, company_id, timezone_id, name, clid, color,
                    color_id, status, terminal_monitoring_enabled,
                    location_control, liveness_enabled, ips,
                    mac_addresses, managers
                )
                SELECT
                    id::BIGINT,
                    company_id::BIGINT,
                    timezone_id::BIGINT,
                    name::TEXT,
                    clid::DOUBLE PRECISION,
                    color::TEXT,
                    color_id::BIGINT,
                    status::BIGINT,
                    terminal_monitoring_enabled::BOOLEAN,
                    location_control::DOUBLE PRECISION,
                    liveness_enabled::BOOLEAN,
                    ips::TEXT,
                    mac_addresses::TEXT,
                    managers::TEXT
                FROM {temp_table_name};
            """
        elif table_name == "positions":
            query = f"""
                INSERT INTO positions (
                    id, company_id, name, clid, color, color_id,
                    status, managers, subdivisions
                )
                SELECT
                    id::BIGINT,
                    company_id::BIGINT,
                    name::TEXT,
                    clid::DOUBLE PRECISION,
                    color::TEXT,
                    color_id::BIGINT,
                    status::BIGINT,
                    managers::TEXT,
                    subdivisions::TEXT
                FROM {temp_table_name};
            """
        elif table_name == "presence_report":
            query = f"""
                INSERT INTO presence_report (
                    employee_id, date, start_time, end_time, is_night_shift,
                    original_estimate, real_estimate, is_red, first_name,
                    last_name, email
                )
                SELECT
                    pr.employee_id::BIGINT,
                    pr.date::TEXT,
                    pr.start_time::TEXT,
                    pr.end_time::TEXT,
                    pr.is_night_shift::BOOLEAN,
                    pr.original_estimate::BIGINT,
                    pr.real_estimate::BIGINT,
                    pr.is_red::BOOLEAN,
                    pr.first_name::TEXT,
                    pr.last_name::TEXT,
                    pr.email::TEXT
                FROM {temp_table_name} AS pr
                JOIN employees AS e ON pr.employee_id::BIGINT = e.id;
            """
        elif table_name == "subdivisions":
            query = f"""
                INSERT INTO subdivisions (
                    id, company_id, name, clid, color, color_id,
                    status, managers, placements
                )
                SELECT
                    id::BIGINT,
                    company_id::BIGINT,
                    name::TEXT,
                    clid::DOUBLE PRECISION,
                    color::TEXT,
                    color_id::BIGINT,
                    status::BIGINT,
                    managers::TEXT,
                    placements::TEXT
                FROM {temp_table_name};
            """
        else:
            logger.warning(f"Таблица {table_name} не поддерживается для вставки")
            return

        # Выполняем вставку новых данных (для таблиц, кроме employees)
        if table_name != "employees":
            connection.execute(text(query))
            logger.info(f"Новые данные вставлены в таблицу {table_name}")

    except Exception as e:
        logger.error(f"Ошибка при очистке и вставке данных в таблицу {table_name}: {str(e)}")
        raise

def process_table(file_path: str, table_name: str):
    """Обработка таблицы: загрузка, очистка и вставка новых данных."""
    temp_table_name = f"{table_name}_temp"
    try:
        # Загружаем данные во временную таблицу
        df = load_csv_to_temp_table(file_path, temp_table_name)
        if df.empty:
            logger.warning(f"Файл {file_path} пуст, пропускаем обработку таблицы {table_name}")
            return

        with engine.begin() as connection:
            # Очищаем таблицу и вставляем новые данные
            clear_and_replace_table(connection, table_name, temp_table_name)

            # Удаляем временную таблицу
            connection.execute(text(f"DROP TABLE IF EXISTS {temp_table_name};"))
            logger.info(f"Временная таблица {temp_table_name} удалена")
    except Exception as e:
        logger.error(f"Ошибка обработки таблицы {table_name}: {str(e)}")
        raise

# Путь к вашим CSV-файлам
data_path = "C:/Users/shish.me/PycharmProjects/MoyGrafik_bot_01/database"

# Информация о таблицах
tables_info = [
    {
        'file_path': f"{data_path}/placements.csv",
        'table_name': 'placements',
    },
    {
        'file_path': f"{data_path}/positions.csv",
        'table_name': 'positions',
    },
    {
        'file_path': f"{data_path}/subdivisions.csv",
        'table_name': 'subdivisions',
    },
    {
        'file_path': f"{data_path}/employees.csv",
        'table_name': 'employees',
    },
    {
        'file_path': f"{data_path}/presence_report.csv",
        'table_name': 'presence_report',
    },
]

# Обработка таблиц в правильном порядке с учётом зависимостей
for info in tables_info:
    table_name = info['table_name']
    logger.info(f"Начало обработки таблицы {table_name}")
    process_table(info['file_path'], table_name)
    logger.info(f"Обработка таблицы {table_name} завершена")