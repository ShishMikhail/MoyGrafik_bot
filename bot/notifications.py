import json
import sys
import os
from datetime import datetime
from telegram.ext import ContextTypes
from sqlalchemy import text
import logging

# Добавляем корень проекта в sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from database.db import engine, user_settings, presence_report, notifications

# Настройка логирования (исправим кодировку позже)
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.DEBUG,
    handlers=[
        logging.FileHandler('notifications.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


async def check_absences(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Проверяет неотмеченный приход, отпуска и отправляет оповещения."""
    # Используем локальное время устройства
    now = datetime.now()
    current_time = now.strftime('%H:%M')
    current_date = now.strftime('%Y-%m-%d')

    logger.debug(f"Запуск проверки отсутствия отметок и отпусков на {current_date} {current_time}")

    with engine.connect() as connection:
        # Получаем всех подписанных пользователей
        query = text("""
            SELECT us.telegram_id, us.employee_id, us.arrival_notification_times, us.vacation_start, us.vacation_end
            FROM user_settings us
            WHERE us.subscribed = TRUE
        """)
        users = connection.execute(query).mappings().fetchall()
        logger.debug(f"Найдено подписанных пользователей: {len(users)}")

        for user in users:
            telegram_id = user['telegram_id']
            employee_id = user['employee_id']

            # Проверяем arrival_notification_times
            try:
                arrival_notification_times = json.loads(user['arrival_notification_times'] or '[]')
                if not isinstance(arrival_notification_times, list):
                    logger.warning(
                        f"Некорректный формат arrival_notification_times для пользователя {telegram_id}: {arrival_notification_times}")
                    continue
            except (json.JSONDecodeError, TypeError) as e:
                logger.error(f"Ошибка при разборе arrival_notification_times для пользователя {telegram_id}: {e}")
                continue

            vacation_start = user['vacation_start']
            vacation_end = user['vacation_end']

            logger.debug(
                f"Пользователь {telegram_id}: arrival_notification_times={arrival_notification_times}, vacation_start={vacation_start}, vacation_end={vacation_end}")

            # Проверяем, находится ли пользователь в отпуске
            if vacation_start and vacation_end:
                try:
                    start = datetime.strptime(vacation_start, '%Y-%m-%d').date()
                    end = datetime.strptime(vacation_end, '%Y-%m-%d').date()
                    current_date_obj = now.date()
                    if start <= current_date_obj <= end:
                        logger.info(
                            f"Пользователь {telegram_id} в отпуске с {vacation_start} по {vacation_end}, пропускаем.")
                        continue
                    else:
                        logger.info(
                            f"Пользователь {telegram_id} не в отпуске: отпуск с {vacation_start} по {vacation_end}")
                except ValueError as ve:
                    logger.warning(
                        f"Неверный формат дат отпуска для пользователя {telegram_id}: start={vacation_start}, end={vacation_end}, ошибка: {str(ve)}")
                    continue

            # Проверяем, есть ли запись о присутствии на сегодня
            query = text("""
                SELECT start_time, end_time
                FROM presence_report
                WHERE employee_id = :employee_id AND date = :date
            """)
            result = connection.execute(query, {"employee_id": employee_id, "date": current_date}).mappings().fetchone()
            logger.debug(f"Запись о присутствии для пользователя {telegram_id} на {current_date}: {result}")

            # Проверяем оповещения о приходе
            if current_time in arrival_notification_times:
                if not result or not result['start_time']:
                    message = f"Оповещение: у тебя нет отметки о приходе на {current_date} в {current_time}."
                    logger.info(f"Отправка оповещения пользователю {telegram_id}: {message}")
                    await context.bot.send_message(chat_id=telegram_id, text=message)

                    # Логируем оповещение
                    query = text("""
                        INSERT INTO notifications (telegram_id, message, sent_at, status)
                        VALUES (:telegram_id, :message, :sent_at, :status)
                    """)
                    connection.execute(query, {
                        "telegram_id": telegram_id,
                        "message": message,
                        "sent_at": now.strftime('%Y-%m-%d %H:%M:%S'),
                        "status": "sent"
                    })
                    connection.commit()
                else:
                    logger.debug(
                        f"Пользователь {telegram_id} уже отметил приход на {current_date}: {result['start_time']}")
            else:
                logger.debug(
                    f"Время {current_time} не совпадает с arrival_notification_times для пользователя {telegram_id}")