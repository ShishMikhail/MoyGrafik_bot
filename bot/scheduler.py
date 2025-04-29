import logging
import sys
import os
from datetime import datetime, date
from sqlalchemy import text
import json

# Добавляем корень проекта в sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from database.db import engine
from bot.status_checker import get_attendance

# Настройка логирования в файл и консоль
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.DEBUG,
    handlers=[
        logging.FileHandler('scheduler.log', encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# Глобальное хранилище для отслеживания отправленных уведомлений
sent_notifications = {
    "last_date": None,  # Последняя дата, для которой отправлялись уведомления
    "arrival": {},  # Уведомления о приходе: {telegram_id: {arrival_time: bool}}
    "departure": {}  # Уведомления об уходе: {telegram_id: {departure_time: bool}}
}

def time_within_range(current_time_str, target_time_str, minutes_range=2):
    """Проверяет, находится ли текущее время в заданном диапазоне (±minutes_range) от целевого."""
    try:
        current = datetime.strptime(current_time_str, '%H:%M')
        target = datetime.strptime(target_time_str, '%H:%M')
        delta = abs((current - target).total_seconds())
        logger.debug(
            f"time_within_range: current={current_time_str}, target={target_time_str}, delta={delta}, result={delta <= minutes_range * 60}")
        return delta <= minutes_range * 60  # Сравниваем в секундах
    except ValueError as e:
        logger.error(f"Ошибка парсинга времени: current={current_time_str}, target={target_time_str}, ошибка: {e}")
        return False

async def send_notification(context):
    """Отправляет уведомления пользователям на основе их настроек, используя локальное время устройства."""
    logger.debug("Проверка: функция send_notification запущена")
    logger.debug(f"Контекст: {context}")

    # Получаем текущее локальное время устройства
    local_now = datetime.now()  # Локальное время устройства
    logger.debug(f"Текущее локальное время устройства: {local_now.strftime('%Y-%m-%d %H:%M:%S')}")
    logger.debug(f"Часовой пояс устройства: {local_now.astimezone().tzinfo}")

    # Используем локальное время устройства
    current_time = local_now.strftime('%H:%M')  # Текущее время в формате ЧЧ:ММ
    current_date = local_now.date()  # Текущая дата как объект date
    current_date_str = local_now.strftime('%Y-%m-%d')  # Текущая дата как строка

    # Проверяем, сменился ли день; если да, сбрасываем хранилище уведомлений
    global sent_notifications
    if sent_notifications["last_date"] != current_date_str:
        logger.debug(
            f"Смена даты: {sent_notifications['last_date']} -> {current_date_str}, сбрасываем хранилище уведомлений")
        sent_notifications = {
            "last_date": current_date_str,
            "arrival": {},
            "departure": {}
        }

    try:
        with engine.connect() as connection:
            # Получаем настройки пользователей (без таймзоны)
            query = text("""
                SELECT us.telegram_id, us.employee_id, us.subscribed, us.arrival_notification_times, 
                       us.departure_notification_times, us.vacation_start, us.vacation_end
                FROM user_settings us
                JOIN employees e ON us.employee_id = e.id
            """)
            users = connection.execute(query).mappings().fetchall()
            logger.debug(f"Найдено пользователей: {len(users)}")
            for user in users:
                logger.debug(f"Пользователь: {user}")
                telegram_id = user['telegram_id']
                employee_id = user['employee_id']
                subscribed = user['subscribed']
                vacation_start = user['vacation_start']
                vacation_end = user['vacation_end']

                logger.debug(f"Обработка пользователя {telegram_id}")

                # Парсим списки уведомлений
                try:
                    arrival_notification_times = json.loads(user['arrival_notification_times'] or '[]')
                    if not isinstance(arrival_notification_times, list):
                        logger.warning(
                            f"Некорректный формат arrival_notification_times для пользователя {telegram_id}: {arrival_notification_times}")
                        arrival_notification_times = []
                except (json.JSONDecodeError, TypeError) as e:
                    logger.error(f"Ошибка при разборе arrival_notification_times для пользователя {telegram_id}: {e}")
                    arrival_notification_times = []

                try:
                    departure_notification_times = json.loads(user['departure_notification_times'] or '[]')
                    if not isinstance(departure_notification_times, list):
                        logger.warning(
                            f"Некорректный формат departure_notification_times для пользователя {telegram_id}: {departure_notification_times}")
                        departure_notification_times = []
                except (json.JSONDecodeError, TypeError) as e:
                    logger.error(f"Ошибка при разборе departure_notification_times для пользователя {telegram_id}: {e}")
                    departure_notification_times = []

                logger.debug(f"Пользователь {telegram_id}, локальное время: {current_time}, дата: {current_date_str}")

                # Проверяем подписку
                if not subscribed:
                    logger.debug(f"Пользователь {telegram_id} не подписан на уведомления.")
                    continue

                # Проверяем, находится ли пользователь в отпуске
                in_vacation = False
                if vacation_start:  # Проверяем, задан ли vacation_start
                    try:
                        # Проверяем тип vacation_start
                        if isinstance(vacation_start, date):
                            start_date = vacation_start
                        else:
                            start_date = datetime.strptime(vacation_start, '%Y-%m-%d').date()

                        # Проверяем тип vacation_end
                        if vacation_end:
                            if isinstance(vacation_end, date):
                                end_date = vacation_end
                            else:
                                end_date = datetime.strptime(vacation_end, '%Y-%m-%d').date()
                        else:
                            end_date = None

                        # Проверяем, находится ли текущая дата в периоде отпуска
                        if start_date <= current_date and (end_date is None or current_date <= end_date):
                            in_vacation = True
                            logger.debug(
                                f"Пользователь {telegram_id} в отпуске с {start_date} по {end_date or 'не указано'}, уведомления не отправляются.")
                            continue
                    except ValueError as e:
                        logger.error(f"Ошибка парсинга дат отпуска для пользователя {telegram_id}: {e}")
                        continue

                # Получаем статус посещения один раз для использования в обоих циклах
                try:
                    status = get_attendance(telegram_id, current_date_str)
                    logger.debug(f"Статус посещения для пользователя {telegram_id}: {status}")
                except Exception as e:
                    logger.error(f"Ошибка в get_attendance для пользователя {telegram_id}: {e}")
                    status = "Неизвестно"

                # Проверяем, есть ли данные о приходе (start_time)
                has_arrival = False
                if status and "Начало: " in status:
                    start_time_str = status.split("Начало: ")[1].split(",")[0].strip()
                    if start_time_str != "не указано":
                        has_arrival = True
                        logger.debug(
                            f"Пользователь {telegram_id} уже отметился в {start_time_str}, уведомления о приходе не отправляются.")

                # Инициализируем хранилище для пользователя, если его нет
                if telegram_id not in sent_notifications["arrival"]:
                    sent_notifications["arrival"][telegram_id] = {}
                if telegram_id not in sent_notifications["departure"]:
                    sent_notifications["departure"][telegram_id] = {}

                # Проверяем уведомления о приходе
                logger.debug(
                    f"Проверка уведомлений о приходе для пользователя {telegram_id}: {arrival_notification_times}")
                for arrival_time in arrival_notification_times:
                    if time_within_range(current_time, arrival_time):
                        if has_arrival:
                            logger.info(
                                f"Уведомление о приходе для пользователя {telegram_id} в {arrival_time} не отправлено, так как пользователь уже отметился.")
                            continue
                        # Проверяем, отправляли ли уже это уведомление
                        if sent_notifications["arrival"][telegram_id].get(arrival_time, False):
                            logger.debug(
                                f"Уведомление о приходе для пользователя {telegram_id} в {arrival_time} уже было отправлено ранее.")
                            continue
                        logger.info(f"Отправка уведомления о приходе для пользователя {telegram_id} в {arrival_time}")
                        # Обновлённый формат сообщения
                        message = "⏰ Не забудьте отметиться перед началом рабочего дня!"
                        try:
                            await context.bot.send_message(chat_id=telegram_id, text=message)
                            logger.debug(f"Уведомление о приходе успешно отправлено пользователю {telegram_id}")
                            # Отмечаем, что уведомление отправлено
                            sent_notifications["arrival"][telegram_id][arrival_time] = True
                        except Exception as e:
                            logger.error(f"Ошибка отправки уведомления о приходе пользователю {telegram_id}: {e}")

                # Проверяем уведомления об уходе
                logger.debug(
                    f"Проверка уведомлений об уходе для пользователя {telegram_id}: {departure_notification_times}")
                for departure_time in departure_notification_times:
                    if time_within_range(current_time, departure_time):
                        # Проверяем, отправляли ли уже это уведомление
                        if sent_notifications["departure"][telegram_id].get(departure_time, False):
                            logger.debug(
                                f"Уведомление об уходе для пользователя {telegram_id} в {departure_time} уже было отправлено ранее.")
                            continue
                        logger.info(f"Отправка уведомления об уходе для пользователя {telegram_id} в {departure_time}")
                        message = f"🚪 Не забудьте отметиться перед уходом в {departure_time}!"
                        try:
                            await context.bot.send_message(chat_id=telegram_id, text=message)
                            logger.debug(f"Уведомление об уходе успешно отправлено пользователю {telegram_id}")
                            # Отмечаем, что уведомление отправлено
                            sent_notifications["departure"][telegram_id][departure_time] = True
                        except Exception as e:
                            logger.error(f"Ошибка отправки уведомления об уходе пользователю {telegram_id}: {e}")

    except Exception as e:
        logger.error(f"Ошибка в send_notification: {str(e)}")
        raise

def setup_scheduler(app):
    """Настраивает планировщик для отправки уведомлений."""
    job_queue = app.job_queue
    job_queue.run_repeating(send_notification, interval=30, first=0)
    logger.info("Планировщик уведомлений настроен с интервалом 30 секунд")