import json
import logging
import sys
import os
import re
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from sqlalchemy import text
from datetime import datetime

# Добавляем корень проекта в sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from database.db import engine
from bot.utils import INPUT_VACATION_START, INPUT_VACATION_END, INPUT_ARRIVAL_NOTIFICATION_TIME, INPUT_DEPARTURE_NOTIFICATION_TIME

# Настройка логирования в консоль PyCharm
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.DEBUG,
    handlers=[
        logging.StreamHandler(sys.stdout)  # Логирование в консоль
    ]
)
logger = logging.getLogger(__name__)

def get_user_settings(telegram_id):
    """Получает настройки пользователя из базы данных."""
    try:
        with engine.connect() as conn:
            query = text("""
                SELECT subscribed, vacation_start, vacation_end, arrival_notification_times, departure_notification_times
                FROM user_settings
                WHERE telegram_id = :telegram_id
            """)
            result = conn.execute(query, {"telegram_id": telegram_id}).mappings().fetchone()
            logger.debug(f"Результат запроса настроек для пользователя {telegram_id}: {result}")

            if not result:
                logger.warning(f"Пользователь {telegram_id} не найден в базе данных")
                return False, None, None, [], []

            subscribed = result['subscribed']
            vacation_start = result['vacation_start']
            vacation_end = result['vacation_end']

            try:
                arrival_notification_times = json.loads(result['arrival_notification_times'] or '[]')
                if not isinstance(arrival_notification_times, list):
                    logger.warning(f"Некорректный формат arrival_notification_times для пользователя {telegram_id}: {arrival_notification_times}")
                    arrival_notification_times = []
            except (json.JSONDecodeError, TypeError) as e:
                logger.error(f"Ошибка при разборе arrival_notification_times для пользователя {telegram_id}: {e}")
                arrival_notification_times = []

            try:
                departure_notification_times = json.loads(result['departure_notification_times'] or '[]')
                if not isinstance(departure_notification_times, list):
                    logger.warning(f"Некорректный формат departure_notification_times для пользователя {telegram_id}: {departure_notification_times}")
                    departure_notification_times = []
            except (json.JSONDecodeError, TypeError) as e:
                logger.error(f"Ошибка при разборе departure_notification_times для пользователя {telegram_id}: {e}")
                departure_notification_times = []

            return subscribed, vacation_start, vacation_end, arrival_notification_times, departure_notification_times

    except Exception as e:
        logger.error(f"Ошибка в get_user_settings для пользователя {telegram_id}: {str(e)}")
        raise

def update_user_settings(telegram_id, subscribed=None, vacation_start=..., vacation_end=..., arrival_notification_times=None, departure_notification_times=None):
    """Обновляет настройки пользователя в базе данных."""
    try:
        with engine.connect() as conn:
            # Проверяем, существует ли пользователь
            query = text("SELECT 1 FROM user_settings WHERE telegram_id = :telegram_id")
            result = conn.execute(query, {"telegram_id": telegram_id}).fetchone()
            if not result:
                logger.warning(f"Пользователь {telegram_id} не найден, невозможно обновить настройки")
                return False

            updates = {}
            params = {"telegram_id": telegram_id}

            # Флаг, чтобы понять, обновляем ли мы vacation_start или vacation_end
            updating_vacation = False

            if subscribed is not None:
                updates["subscribed"] = "subscribed = :subscribed"
                params["subscribed"] = subscribed

            # Изменил логику: теперь vacation_start и vacation_end обрабатываются даже если передан None
            if vacation_start is not ...:  # Проверяем, был ли передан параметр (используем ... как sentinel)
                updates["vacation_start"] = "vacation_start = :vacation_start"
                params["vacation_start"] = vacation_start
                updating_vacation = True

            if vacation_end is not ...:
                updates["vacation_end"] = "vacation_end = :vacation_end"
                params["vacation_end"] = vacation_end
                updating_vacation = True

            if arrival_notification_times is not None:
                updates["arrival_notification_times"] = "arrival_notification_times = :arrival_notification_times"
                params["arrival_notification_times"] = json.dumps(arrival_notification_times)

            if departure_notification_times is not None:
                updates["departure_notification_times"] = "departure_notification_times = :departure_notification_times"
                params["departure_notification_times"] = json.dumps(departure_notification_times)

            if not updates:
                logger.warning(f"Нет данных для обновления настроек пользователя {telegram_id}")
                return False

            update_clause = ", ".join(updates.values())
            query = text(f"""
                UPDATE user_settings
                SET {update_clause}
                WHERE telegram_id = :telegram_id
            """)
            logger.debug(f"Выполняется запрос обновления для пользователя {telegram_id}: {query}, параметры: {params}")
            conn.execute(query, params)
            conn.commit()  # Явно фиксируем транзакцию
            logger.info(f"Настройки пользователя {telegram_id} успешно обновлены: {params}")

            # Проверка после обновления
            query = text("""
                SELECT subscribed, vacation_start, vacation_end, arrival_notification_times, departure_notification_times
                FROM user_settings
                WHERE telegram_id = :telegram_id
            """)
            result = conn.execute(query, {"telegram_id": telegram_id}).mappings().fetchone()
            logger.debug(f"Проверка после обновления для пользователя {telegram_id}: {result}")

            # Проверяем сброс vacation_start и vacation_end только если мы их обновляли
            if updating_vacation and vacation_start is None and vacation_end is None:
                if result['vacation_start'] is not None or result['vacation_end'] is not None:
                    logger.error(f"Ошибка: vacation_start или vacation_end не сброшены в NULL для пользователя {telegram_id}: {result}")
                    return False

            # Проверяем, что arrival_notification_times обновлены
            if arrival_notification_times is not None:
                updated_arrival_times = json.loads(result['arrival_notification_times'] or '[]')
                if updated_arrival_times != arrival_notification_times:
                    logger.error(f"Ошибка: arrival_notification_times не обновлены для пользователя {telegram_id}. Ожидалось: {arrival_notification_times}, получено: {updated_arrival_times}")
                    return False

            # Проверяем, что departure_notification_times обновлены
            if departure_notification_times is not None:
                updated_departure_times = json.loads(result['departure_notification_times'] or '[]')
                if updated_departure_times != departure_notification_times:
                    logger.error(f"Ошибка: departure_notification_times не обновлены для пользователя {telegram_id}. Ожидалось: {departure_notification_times}, получено: {updated_departure_times}")
                    return False

            return True

    except Exception as e:
        logger.error(f"Ошибка в update_user_settings для пользователя {telegram_id}: {str(e)}")
        return False

def create_main_menu(subscribed, vacation_start, vacation_end, arrival_notification_times, departure_notification_times):
    """Создаёт главное меню с текущими настройками пользователя."""
    subscription_status = "подписан ✅" if subscribed else "не подписан 🚫"
    vacation_text = f"{vacation_start} - {vacation_end}" if vacation_start and vacation_end else "не задано 📅"
    arrival_notifications_text = ', '.join(arrival_notification_times) if arrival_notification_times else "не задано ⏰"
    departure_notifications_text = ', '.join(departure_notification_times) if departure_notification_times else "не задано 🚪"

    message = (
        f"📋 Твои текущие настройки:\n"
        f"📩 Подписка на рассылку: {subscription_status}\n"
        f"🏖️ Период отпуска: {vacation_text}\n"
        f"⏰ Время оповещений о приходе: {arrival_notifications_text}\n"
        f"🚪 Время оповещений об уходе: {departure_notifications_text}\n\n"
        "Выбери, что хочешь сделать: 👇"
    )
    keyboard = [
        [InlineKeyboardButton("📩 Подписка на рассылку", callback_data='toggle_subscription')],
        [InlineKeyboardButton("🏖️ Установить период отпуска", callback_data='set_vacation'),
         InlineKeyboardButton("🗑️ Удалить период отпуска", callback_data='remove_vacation')],
        [InlineKeyboardButton("⏰ Добавить время оповещений о приходе", callback_data='add_arrival_notification_time'),
         InlineKeyboardButton("🗑️ Удалить время оповещений о приходе", callback_data='remove_arrival_notification_time')],
        [InlineKeyboardButton("🚪 Добавить время оповещений об уходе", callback_data='add_departure_notification_time'),
         InlineKeyboardButton("🗑️ Удалить время оповещений об уходе", callback_data='remove_departure_notification_time')],
        [InlineKeyboardButton("📅 Посещения за сегодня", callback_data='attendance_today'),
         InlineKeyboardButton("📊 Посещения за 10 дней", callback_data='attendance_10_days')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    return message, reply_markup

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    callback_data = query.data
    logger.debug(f"Получен callback-запрос от пользователя {user_id}: callback_data={callback_data}")

    try:
        subscribed, vacation_start, vacation_end, arrival_notification_times, departure_notification_times = get_user_settings(user_id)

        if callback_data == 'toggle_subscription':
            logger.info(f"Пользователь {user_id} нажал кнопку 'Подписка на рассылку'. Действие: переключение статуса подписки.")
            new_subscribed = not subscribed
            success = update_user_settings(user_id, subscribed=new_subscribed)
            if success:
                status = "подписан ✅" if new_subscribed else "отписан 🚫"
                await query.message.reply_text(f"📩 Подписка на рассылку: {status}")
                # Обновляем меню
                subscribed, vacation_start, vacation_end, arrival_notification_times, departure_notification_times = get_user_settings(user_id)
                message, reply_markup = create_main_menu(subscribed, vacation_start, vacation_end, arrival_notification_times, departure_notification_times)
                await query.message.reply_text(message, reply_markup=reply_markup)
            else:
                logger.error(f"Не удалось обновить статус подписки для пользователя {user_id}")
                await query.message.reply_text("❌ Ошибка при обновлении подписки. Попробуй снова.")

        elif callback_data == 'set_vacation':
            logger.info(f"Пользователь {user_id} нажал кнопку 'Установить период отпуска'. Действие: запрос даты начала отпуска.")
            await query.message.reply_text("📅 Введи дату начала отпуска в формате ДД-ММ-ГГГГ (например, 01-01-2025):")
            return INPUT_VACATION_START

        elif callback_data == 'remove_vacation':
            logger.info(f"Пользователь {user_id} нажал кнопку 'Удалить период отпуска'. Действие: удаление периода отпуска.")
            if not vacation_start and not vacation_end:
                logger.warning(f"У пользователя {user_id} нет установленного периода отпуска.")
                await query.message.reply_text("🏖️ У тебя нет установленного периода отпуска! 😕")
                return ConversationHandler.END
            success = update_user_settings(user_id, vacation_start=None, vacation_end=None)
            if success:
                await query.message.reply_text("🏖️ Период отпуска удалён! ✅")
                # Обновляем меню
                subscribed, vacation_start, vacation_end, arrival_notification_times, departure_notification_times = get_user_settings(user_id)
                message, reply_markup = create_main_menu(subscribed, vacation_start, vacation_end, arrival_notification_times, departure_notification_times)
                await query.message.reply_text(message, reply_markup=reply_markup)
            else:
                logger.error(f"Не удалось удалить период отпуска для пользователя {user_id}")
                await query.message.reply_text("❌ Ошибка при удалении периода отпуска. Попробуй снова.")

        elif callback_data == 'add_arrival_notification_time':
            logger.info(f"Пользователь {user_id} нажал кнопку 'Добавить время оповещений о приходе'. Действие: проверка лимита и запрос времени.")
            if len(arrival_notification_times) >= 10:
                logger.warning(f"Пользователь {user_id} достиг лимита времени оповещений о приходе (10).")
                await query.message.reply_text(
                    "⏰ Достигнуто максимальное количество оповещений о приходе (10). Удали одно из существующих! 🗑️")
                return ConversationHandler.END
            await query.message.reply_text("⏰ Введи время оповещения о приходе в формате ЧЧ:ММ или Ч:ММ (например, 09:00 или 9:00):")
            return INPUT_ARRIVAL_NOTIFICATION_TIME

        elif callback_data == 'remove_arrival_notification_time':
            logger.info(f"Пользователь {user_id} нажал кнопку 'Удалить время оповещений о приходе'. Действие: отображение списка для удаления.")
            if not arrival_notification_times:
                logger.warning(f"У пользователя {user_id} нет установленных времен оповещений о приходе.")
                await query.message.reply_text("⏰ У тебя нет установленных времен оповещений о приходе! 😕")
                return ConversationHandler.END
            keyboard = [[InlineKeyboardButton(f"{time} 🗑️", callback_data=f"remove_arrival_time_{time}")] for time in arrival_notification_times]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.message.reply_text("⏰ Выбери время оповещения о приходе для удаления: 👇", reply_markup=reply_markup)

        elif callback_data.startswith('remove_arrival_time_'):
            logger.info(f"Пользователь {user_id} нажал кнопку удаления времени оповещения о приходе: {callback_data}. Действие: удаление времени.")
            time_to_remove = callback_data[len('remove_arrival_time_'):]
            if time_to_remove in arrival_notification_times:
                arrival_notification_times.remove(time_to_remove)
                success = update_user_settings(user_id, arrival_notification_times=arrival_notification_times)
                if success:
                    await query.message.reply_text(f"⏰ Время оповещения о приходе {time_to_remove} удалено! ✅")
                    # Обновляем меню
                    subscribed, vacation_start, vacation_end, arrival_notification_times, departure_notification_times = get_user_settings(user_id)
                    message, reply_markup = create_main_menu(subscribed, vacation_start, vacation_end, arrival_notification_times, departure_notification_times)
                    await query.message.reply_text(message, reply_markup=reply_markup)
                else:
                    logger.error(f"Не удалось удалить время оповещения о приходе {time_to_remove} для пользователя {user_id}")
                    await query.message.reply_text("❌ Ошибка при удалении времени оповещения. Попробуй снова.")
            else:
                await query.message.reply_text("⏰ Это время уже удалено! 😕")

        elif callback_data == 'add_departure_notification_time':
            logger.info(f"Пользователь {user_id} нажал кнопку 'Добавить время оповещений об уходе'. Действие: проверка лимита и запрос времени.")
            if len(departure_notification_times) >= 10:
                logger.warning(f"Пользователь {user_id} достиг лимита времени оповещений об уходе (10).")
                await query.message.reply_text(
                    "🚪 Достигнуто максимальное количество оповещений об уходе (10). Удали одно из существующих! 🗑️")
                return ConversationHandler.END
            await query.message.reply_text("🚪 Введи время оповещения об уходе в формате ЧЧ:ММ или Ч:ММ (например, 17:00 или 9:00):")
            return INPUT_DEPARTURE_NOTIFICATION_TIME

        elif callback_data == 'remove_departure_notification_time':
            logger.info(f"Пользователь {user_id} нажал кнопку 'Удалить время оповещений об уходе'. Действие: отображение списка для удаления.")
            if not departure_notification_times:
                logger.warning(f"У пользователя {user_id} нет установленных времен оповещений об уходе.")
                await query.message.reply_text("🚪 У тебя нет установленных времен оповещений об уходе! 😕")
                return ConversationHandler.END
            keyboard = [[InlineKeyboardButton(f"{time} 🗑️", callback_data=f"remove_departure_time_{time}")] for time in departure_notification_times]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.message.reply_text("🚪 Выбери время оповещения об уходе для удаления: 👇", reply_markup=reply_markup)

        elif callback_data.startswith('remove_departure_time_'):
            logger.info(f"Пользователь {user_id} нажал кнопку удаления времени оповещения об уходе: {callback_data}. Действие: удаление времени.")
            time_to_remove = callback_data[len('remove_departure_time_'):]
            if time_to_remove in departure_notification_times:
                departure_notification_times.remove(time_to_remove)
                success = update_user_settings(user_id, departure_notification_times=departure_notification_times)
                if success:
                    await query.message.reply_text(f"🚪 Время оповещения об уходе {time_to_remove} удалено! ✅")
                    # Обновляем меню
                    subscribed, vacation_start, vacation_end, arrival_notification_times, departure_notification_times = get_user_settings(user_id)
                    message, reply_markup = create_main_menu(subscribed, vacation_start, vacation_end, arrival_notification_times, departure_notification_times)
                    await query.message.reply_text(message, reply_markup=reply_markup)
                else:
                    logger.error(f"Не удалось удалить время оповещения об уходе {time_to_remove} для пользователя {user_id}")
                    await query.message.reply_text("❌ Ошибка при удалении времени оповещения. Попробуй снова.")
            else:
                await query.message.reply_text("🚪 Это время уже удалено! 😕")

        return ConversationHandler.END

    except Exception as e:
        logger.error(f"Ошибка в button_handler для пользователя {user_id}: {str(e)}")
        await query.message.reply_text("❌ Произошла ошибка. Попробуй снова или свяжись с администратором.")
        return ConversationHandler.END

async def set_vacation_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text
    logger.debug(f"Пользователь {user_id} ввёл дату начала отпуска: {text}")

    try:
        vacation_start = datetime.strptime(text, '%d-%m-%Y').strftime('%Y-%m-%d')
        logger.info(f"Дата начала отпуска успешно распарсена: {vacation_start}")
        today = datetime.now().date()
        start_date = datetime.strptime(vacation_start, '%Y-%m-%d').date()
        if start_date < today:
            logger.warning(f"Дата начала отпуска в прошлом: {vacation_start}, текущая дата: {today}")
            await update.message.reply_text("❌ Дата начала отпуска не может быть в прошлом. Попробуй снова (ДД-ММ-ГГГГ, например, 01-01-2025):")
            return INPUT_VACATION_START
        context.user_data['vacation_start'] = vacation_start
        await update.message.reply_text("📅 Введи дату окончания отпуска в формате ДД-ММ-ГГГГ (например, 01-01-2025):")
        logger.info(f"Пользователь {user_id} перешёл в состояние INPUT_VACATION_END")
        return INPUT_VACATION_END
    except ValueError as e:
        logger.error(f"Ошибка парсинга даты начала отпуска для пользователя {user_id}: {str(e)}")
        await update.message.reply_text("❌ Неверный формат даты. Попробуй ещё раз (ДД-ММ-ГГГГ, например, 01-01-2025):")
        return INPUT_VACATION_START
    except Exception as e:
        logger.error(f"Неожиданная ошибка в set_vacation_start для пользователя {user_id}: {str(e)}")
        await update.message.reply_text("❌ Произошла ошибка. Попробуй снова или свяжись с администратором.")
        return ConversationHandler.END

async def set_vacation_end(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text
    logger.debug(f"Пользователь {user_id} ввёл дату окончания отпуска: {text}")

    try:
        vacation_end = datetime.strptime(text, '%d-%m-%Y').strftime('%Y-%m-%d')
        logger.info(f"Дата окончания отпуска успешно распарсена: {vacation_end}")
        vacation_start = context.user_data.get('vacation_start')
        if not vacation_start:
            await update.message.reply_text("❌ Произошла ошибка. Начни заново с помощью кнопки 'Установить период отпуска'. 😕")
            return ConversationHandler.END

        start_date = datetime.strptime(vacation_start, '%Y-%m-%d').date()
        end_date = datetime.strptime(vacation_end, '%Y-%m-%d').date()
        if end_date <= start_date:
            await update.message.reply_text("❌ Дата окончания отпуска должна быть позже даты начала. Попробуй ещё раз (ДД-ММ-ГГГГ):")
            return INPUT_VACATION_END

        success = update_user_settings(user_id, vacation_start=vacation_start, vacation_end=vacation_end)
        if success:
            await update.message.reply_text(f"🏖️ Период отпуска {vacation_start} - {vacation_end} установлен! ✅")
            subscribed, vacation_start, vacation_end, arrival_notification_times, departure_notification_times = get_user_settings(user_id)
            message, reply_markup = create_main_menu(subscribed, vacation_start, vacation_end, arrival_notification_times, departure_notification_times)
            await update.message.reply_text(message, reply_markup=reply_markup)
        else:
            await update.message.reply_text("❌ Ошибка при установке периода отпуска. Попробуй снова.")
        return ConversationHandler.END
    except ValueError as e:
        logger.error(f"Ошибка парсинга даты окончания отпуска для пользователя {user_id}: {str(e)}")
        await update.message.reply_text("❌ Неверный формат даты. Попробуй ещё раз (ДД-ММ-ГГГГ, например, 01-01-2025):")
        return INPUT_VACATION_END
    except Exception as e:
        logger.error(f"Неожиданная ошибка в set_vacation_end для пользователя {user_id}: {str(e)}")
        await update.message.reply_text("❌ Произошла ошибка. Попробуй снова или свяжись с администратором.")
        return ConversationHandler.END

async def add_arrival_notification_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()
    logger.debug(f"Пользователь {user_id} ввёл время оповещения о приходе: {text}")

    try:
        # Проверяем формат времени с помощью регулярного выражения
        time_pattern = r'^(?:[0-1]?[0-9]|2[0-3]):[0-5][0-9]$|^(?:[0-9]|1[0-2]):[0-5][0-9]$'
        if not re.match(time_pattern, text):
            logger.error(f"Неверный формат времени оповещения о приходе для пользователя {user_id}: {text}")
            await update.message.reply_text("❌ Неверный формат времени. Попробуй ещё раз (ЧЧ:ММ или Ч:ММ, например, 09:00 или 9:00):")
            return INPUT_ARRIVAL_NOTIFICATION_TIME

        # Нормализуем время в формат ЧЧ:ММ
        parts = text.split(':')
        hours = int(parts[0])
        minutes = int(parts[1])
        if hours < 0 or hours > 23 or minutes < 0 or minutes > 59:
            raise ValueError("Часы должны быть от 0 до 23, минуты от 00 до 59")
        time_str = f"{hours:02d}:{minutes:02d}"
        logger.info(f"Время оповещения о приходе успешно нормализовано: {time_str}")

        subscribed, vacation_start, vacation_end, arrival_notification_times, departure_notification_times = get_user_settings(user_id)

        if time_str in arrival_notification_times:
            await update.message.reply_text(f"⏰ Время оповещения о приходе {time_str} уже добавлено! 😕")
            return ConversationHandler.END

        arrival_notification_times.append(time_str)
        success = update_user_settings(user_id, arrival_notification_times=arrival_notification_times)
        if success:
            await update.message.reply_text(f"⏰ Время оповещения о приходе {time_str} добавлено! ✅")
            subscribed, vacation_start, vacation_end, arrival_notification_times, departure_notification_times = get_user_settings(user_id)
            message, reply_markup = create_main_menu(subscribed, vacation_start, vacation_end, arrival_notification_times, departure_notification_times)
            await update.message.reply_text(message, reply_markup=reply_markup)
        else:
            logger.error(f"Не удалось добавить время оповещения о приходе {time_str} для пользователя {user_id}")
            await update.message.reply_text("❌ Ошибка при добавлении времени оповещения. Попробуй снова.")
        return ConversationHandler.END
    except ValueError as e:
        logger.error(f"Ошибка обработки времени оповещения о приходе для пользователя {user_id}: {str(e)}")
        await update.message.reply_text("❌ Неверный формат времени. Попробуй ещё раз (ЧЧ:ММ или Ч:ММ, например, 09:00 или 9:00):")
        return INPUT_ARRIVAL_NOTIFICATION_TIME
    except Exception as e:
        logger.error(f"Неожиданная ошибка в add_arrival_notification_time для пользователя {user_id}: {str(e)}")
        await update.message.reply_text("❌ Произошла ошибка. Попробуй снова или свяжись с администратором.")
        return ConversationHandler.END

async def add_departure_notification_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()
    logger.debug(f"Пользователь {user_id} ввёл время оповещения об уходе: {text}")

    try:
        # Проверяем формат времени с помощью регулярного выражения
        time_pattern = r'^(?:[0-1]?[0-9]|2[0-3]):[0-5][0-9]$|^(?:[0-9]|1[0-2]):[0-5][0-9]$'
        if not re.match(time_pattern, text):
            logger.error(f"Неверный формат времени оповещения об уходе для пользователя {user_id}: {text}")
            await update.message.reply_text("❌ Неверный формат времени. Попробуй ещё раз (ЧЧ:ММ или Ч:ММ, например, 17:00 или 9:00):")
            return INPUT_DEPARTURE_NOTIFICATION_TIME

        # Нормализуем время в формат ЧЧ:ММ
        parts = text.split(':')
        hours = int(parts[0])
        minutes = int(parts[1])
        if hours < 0 or hours > 23 or minutes < 0 or minutes > 59:
            raise ValueError("Часы должны быть от 0 до 23, минуты от 00 до 59")
        time_str = f"{hours:02d}:{minutes:02d}"
        logger.info(f"Время оповещения об уходе успешно нормализовано: {time_str}")

        subscribed, vacation_start, vacation_end, arrival_notification_times, departure_notification_times = get_user_settings(user_id)

        if time_str in departure_notification_times:
            await update.message.reply_text(f"🚪 Время оповещения об уходе {time_str} уже добавлено! 😕")
            return ConversationHandler.END

        departure_notification_times.append(time_str)
        success = update_user_settings(user_id, departure_notification_times=departure_notification_times)
        if success:
            await update.message.reply_text(f"🚪 Время оповещения об уходе {time_str} добавлено! ✅")
            subscribed, vacation_start, vacation_end, arrival_notification_times, departure_notification_times = get_user_settings(user_id)
            message, reply_markup = create_main_menu(subscribed, vacation_start, vacation_end, arrival_notification_times, departure_notification_times)
            await update.message.reply_text(message, reply_markup=reply_markup)
        else:
            logger.error(f"Не удалось добавить время оповещения об уходе {time_str} для пользователя {user_id}")
            await update.message.reply_text("❌ Ошибка при добавлении времени оповещения. Попробуй снова.")
        return ConversationHandler.END
    except ValueError as e:
        logger.error(f"Ошибка обработки времени оповещения об уходе для пользователя {user_id}: {str(e)}")
        await update.message.reply_text("❌ Неверный формат времени. Попробуй ещё раз (ЧЧ:ММ или Ч:ММ, например, 17:00 или 9:00):")
        return INPUT_DEPARTURE_NOTIFICATION_TIME
    except Exception as e:
        logger.error(f"Неожиданная ошибка в add_departure_notification_time для пользователя {user_id}: {str(e)}")
        await update.message.reply_text("❌ Произошла ошибка. Попробуй снова или свяжись с администратором.")
        return ConversationHandler.END