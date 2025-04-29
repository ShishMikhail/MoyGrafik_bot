import logging
import sys
import os
from telegram import Update
from telegram.ext import ContextTypes
from sqlalchemy import text

# Добавляем корень проекта в sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from database.db import engine

# Настройка логирования только в файл
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.DEBUG,
    handlers=[
        logging.FileHandler('register.log', encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)

async def register(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает команду /register для регистрации пользователя."""
    user_id = update.effective_user.id
    first_name = update.effective_user.first_name
    last_name = update.effective_user.last_name or ''
    logger.debug(f"Получена команда /register от пользователя {user_id}")

    try:
        with engine.connect() as connection:
            # Проверяем, есть ли пользователь уже в базе
            query = text("SELECT employee_id FROM user_settings WHERE telegram_id = :telegram_id")
            result = connection.execute(query, {"telegram_id": user_id}).fetchone()

            if result:
                logger.info(f"Пользователь {user_id} уже зарегистрирован")
                await update.message.reply_text("✅ Ты уже зарегистрирован! Используй /start, чтобы открыть меню.")
                return

            # Добавляем пользователя в таблицу user_settings
            # Для упрощения предполагаем, что employee_id будет совпадать с telegram_id
            # В реальном приложении здесь должна быть логика привязки к сотруднику
            query = text("""
                INSERT INTO user_settings (telegram_id, employee_id, subscribed, arrival_notification_times, departure_notification_times)
                VALUES (:telegram_id, :employee_id, FALSE, '[]', '[]')
                ON CONFLICT (telegram_id) DO NOTHING
            """)
            connection.execute(query, {"telegram_id": user_id, "employee_id": user_id})
            connection.commit()

            # Добавляем данные сотрудника в таблицу employees (если нужно)
            query = text("""
                INSERT INTO employees (id, first_name, last_name)
                VALUES (:id, :first_name, :last_name)
                ON CONFLICT (id) DO NOTHING
            """)
            connection.execute(query, {"id": user_id, "first_name": first_name, "last_name": last_name})
            connection.commit()

            logger.info(f"Пользователь {user_id} успешно зарегистрирован")
            await update.message.reply_text(
                "🎉 Регистрация прошла успешно!\n"
                "Теперь ты можешь использовать команды:\n"
                "/start — открыть меню\n"
                "/menu — посмотреть настройки\n"
                "/status — узнать текущий статус"
            )

    except Exception as e:
        logger.error(f"Ошибка при регистрации пользователя {user_id}: {str(e)}")
        await update.message.reply_text("❌ Произошла ошибка при регистрации. Попробуй снова или свяжись с администратором.")