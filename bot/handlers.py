import logging
import sys
import os
import re
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from datetime import datetime
from sqlalchemy import text
import json

# Добавляем корень проекта в sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from bot.settings import get_user_settings, update_user_settings
from bot.status_checker import get_attendance, get_attendance_last_10_days
from bot.utils import INPUT_VACATION_START, INPUT_VACATION_END, INPUT_ARRIVAL_NOTIFICATION_TIME, \
    INPUT_DEPARTURE_NOTIFICATION_TIME
from database.db import engine

# Настройка логирования только в файл
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.DEBUG,
    handlers=[
        logging.FileHandler('handlers.log', encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)

# Состояния для ConversationHandler
SET_VACATION_START, SET_VACATION_END, ADD_ARRIVAL_NOTIFICATION, ADD_DEPARTURE_NOTIFICATION = range(INPUT_VACATION_START,
                                                                                                   INPUT_DEPARTURE_NOTIFICATION_TIME + 1)


def create_main_menu(subscribed, vacation_start, vacation_end, arrival_notification_times,
                     departure_notification_times):
    """Создаёт главное меню с текущими настройками пользователя."""
    subscription_status = "подписан ✅" if subscribed else "не подписан 🚫"
    vacation_text = f"{vacation_start} - {vacation_end}" if vacation_start and vacation_end else "не задано 📅"
    arrival_notifications_text = ', '.join(arrival_notification_times) if arrival_notification_times else "не задано ⏰"
    departure_notifications_text = ', '.join(
        departure_notification_times) if departure_notification_times else "не задано 🚪"

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
         InlineKeyboardButton("🗑️ Удалить время оповещений о приходе",
                              callback_data='remove_arrival_notification_time')],
        [InlineKeyboardButton("🚪 Добавить время оповещений об уходе", callback_data='add_departure_notification_time'),
         InlineKeyboardButton("🗑️ Удалить время оповещений об уходе",
                              callback_data='remove_departure_notification_time')],
        [InlineKeyboardButton("📅 Посещения за сегодня", callback_data='attendance_today'),
         InlineKeyboardButton("📊 Посещения за 10 дней", callback_data='attendance_10_days')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    return message, reply_markup


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    logger.debug(f"Получена команда /start от пользователя {user_id}")

    # Принудительно завершаем любой текущий диалог и очищаем данные
    context.user_data.clear()
    # Устанавливаем состояние ConversationHandler в завершенное
    context.user_data['conversation_state'] = None

    # Создаём кнопки
    keyboard = [
        [InlineKeyboardButton("📩 Подписка на рассылку", callback_data='toggle_subscription')],
        [InlineKeyboardButton("🏖️ Установить период отпуска", callback_data='set_vacation'),
         InlineKeyboardButton("🗑️ Удалить период отпуска", callback_data='remove_vacation')],
        [InlineKeyboardButton("⏰ Добавить время оповещений о приходе", callback_data='add_arrival_notification_time'),
         InlineKeyboardButton("🗑️ Удалить время оповещений о приходе",
                              callback_data='remove_arrival_notification_time')],
        [InlineKeyboardButton("🚪 Добавить время оповещений об уходе", callback_data='add_departure_notification_time'),
         InlineKeyboardButton("🗑️ Удалить время оповещений об уходе",
                              callback_data='remove_departure_notification_time')],
        [InlineKeyboardButton("📅 Посещения за сегодня", callback_data='attendance_today'),
         InlineKeyboardButton("📊 Посещения за 10 дней", callback_data='attendance_10_days')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    # Проверяем пользователя в базе данных
    try:
        with engine.connect() as connection:
            query = text("SELECT employee_id FROM user_settings WHERE telegram_id = :telegram_id")
            result = connection.execute(query, {"telegram_id": user_id}).mappings().fetchone()

            if not result:
                message = (
                    "👋 Привет! Я твой бот для управления графиком работы.\n\n"
                    "❌ Кажется, ты ещё не зарегистрирован.\n"
                    "Используй команду /register, чтобы начать! 📝"
                )
                await update.message.reply_text(message, reply_markup=reply_markup)
                return ConversationHandler.END

            employee_id = result['employee_id']

            query = text("SELECT first_name, last_name FROM employees réactions: WHERE id = :employee_id")
            employee = connection.execute(query, {"employee_id": employee_id}).mappings().fetchone()

            if not employee:
                message = (
                    "👋 Привет! Я твой бот для управления графиком работы.\n\n"
                    "❌ Не удалось найти твои данные. Возможно, сотрудник не привязан.\n"
                    "Попробуй перерегистрироваться с помощью /register. 📝"
                )
                await update.message.reply_text(message, reply_markup=reply_markup)
                return ConversationHandler.END

            first_name = employee['first_name']
            last_name = employee['last_name']

        subscribed, vacation_start, vacation_end, arrival_notification_times, departure_notification_times = get_user_settings(
            user_id)

        message, reply_markup = create_main_menu(subscribed, vacation_start, vacation_end, arrival_notification_times,
                                                 departure_notification_times)
        message = (
            f"👋 Привет, {first_name} {last_name}! Я твой бот для управления графиком работы.\n\n"
            f"{message}"
        )

        await update.message.reply_text(message, reply_markup=reply_markup)
        return ConversationHandler.END

    except Exception as e:
        logger.error(f"Ошибка при выполнении команды /start для пользователя {user_id}: {str(e)}")
        await update.message.reply_text("❌ Произошла ошибка. Попробуй снова или свяжись с администратором.")
        return ConversationHandler.END


async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    logger.debug(f"Получена команда /menu от пользователя {user_id}")

    # Принудительно завершаем любой текущий диалог и очищаем данные
    context.user_data.clear()
    context.user_data['conversation_state'] = None

    try:
        subscribed, vacation_start, vacation_end, arrival_notification_times, departure_notification_times = get_user_settings(
            user_id)

        message, reply_markup = create_main_menu(subscribed, vacation_start, vacation_end, arrival_notification_times,
                                                 departure_notification_times)

        await update.message.reply_text(message, reply_markup=reply_markup)
        return ConversationHandler.END

    except Exception as e:
        logger.error(f"Ошибка при выполнении команды /menu для пользователя {user_id}: {str(e)}")
        await update.message.reply_text("❌ Произошла ошибка. Попробуй снова или свяжись с администратором.")
        return ConversationHandler.END


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    logger.debug(f"Получена команда /status от пользователя {user_id}")

    try:
        subscribed, vacation_start, vacation_end, arrival_notification_times, departure_notification_times = get_user_settings(
            user_id)

        subscription_status = "подписан ✅" if subscribed else "не подписан 🚫"
        vacation_text = f"{vacation_start} - {vacation_end}" if vacation_start and vacation_end else "не задано 📅"
        arrival_notifications_text = ', '.join(
            arrival_notification_times) if arrival_notification_times else "не задано ⏰"
        departure_notifications_text = ', '.join(
            departure_notification_times) if departure_notification_times else "не задано 🚪"

        message = (
            "📋 Твой текущий статус:\n\n"
            f"📩 Подписка на рассылку: {subscription_status}\n"
            f"🏖️ Период отпуска: {vacation_text}\n"
            f"⏰ Время оповещений о приходе: {arrival_notifications_text}\n"
            f"🚪 Время оповещений об уходе: {departure_notifications_text}"
        )

        await update.message.reply_text(message)
        return ConversationHandler.END

    except Exception as e:
        logger.error(f"Ошибка при выполнении команды /status для пользователя {user_id}: {str(e)}")
        await update.message.reply_text("❌ Произошла ошибка. Попробуй снова или свяжись с администратором.")
        return ConversationHandler.END


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    callback_data = query.data
    logger.debug(f"Получен callback-запрос от пользователя {user_id}: callback_data={callback_data}")

    try:
        subscribed, vacation_start, vacation_end, arrival_notification_times, departure_notification_times = get_user_settings(
            user_id)
        logger.debug(
            f"Текущие настройки пользователя {user_id}: subscribed={subscribed}, vacation_start={vacation_start}, vacation_end={vacation_end}, arrival_notification_times={arrival_notification_times}, departure_notification_times={departure_notification_times}")

        if callback_data == 'toggle_subscription':
            logger.info(
                f"Пользователь {user_id} нажал кнопку 'Подписка на рассылку'. Действие: переключение статуса подписки.")
            new_subscribed = not subscribed
            success = update_user_settings(user_id, subscribed=new_subscribed)
            if not success:
                logger.error(f"Не удалось обновить статус подписки для пользователя {user_id}")
                await query.message.reply_text("❌ Ошибка при обновлении подписки. Попробуй снова.")
                return ConversationHandler.END

            logger.info(f"Статус подписки пользователя {user_id} изменён на {new_subscribed}")
            status = "подписан ✅" if new_subscribed else "отписан 🚫"
            await query.message.reply_text(f"📩 Подписка на рассылку: {status}")

            # Обновляем меню после изменения статуса подписки
            subscribed, vacation_start, vacation_end, arrival_notification_times, departure_notification_times = get_user_settings(
                user_id)
            message, reply_markup = create_main_menu(subscribed, vacation_start, vacation_end,
                                                     arrival_notification_times, departure_notification_times)
            await query.message.reply_text(message, reply_markup=reply_markup)

        elif callback_data == 'set_vacation':
            logger.info(
                f"Пользователь {user_id} нажал кнопку 'Установить период отпуска'. Действие: запрос даты начала отпуска.")
            await query.message.reply_text("📅 Введи дату начала отпуска в формате ДД-ММ-ГГГГ (например, 01-01-2025):")
            logger.info(f"Пользователь {user_id} перешёл в состояние SET_VACATION_START")
            return SET_VACATION_START

        elif callback_data == 'remove_vacation':
            logger.info(
                f"Пользователь {user_id} нажал кнопку 'Удалить период отпуска'. Действие: удаление периода отпуска.")
            if not vacation_start and not vacation_end:
                logger.warning(f"У пользователя {user_id} нет установленного периода отпуска.")
                await query.message.reply_text("🏖️ У тебя нет установленного периода отпуска! 😕")
                return ConversationHandler.END
            success = update_user_settings(user_id, vacation_start=None, vacation_end=None)
            if not success:
                logger.error(f"Не удалось удалить период отпуска для пользователя {user_id}")
                await query.message.reply_text("❌ Ошибка при удалении периода отпуска. Попробуй снова.")
                return ConversationHandler.END

            await query.message.reply_text("🏖️ Период отпуска удалён! ✅")

            # Обновляем меню после удаления периода отпуска
            subscribed, vacation_start, vacation_end, arrival_notification_times, departure_notification_times = get_user_settings(
                user_id)
            message, reply_markup = create_main_menu(subscribed, vacation_start, vacation_end,
                                                     arrival_notification_times, departure_notification_times)
            await query.message.reply_text(message, reply_markup=reply_markup)

        elif callback_data == 'add_arrival_notification_time':
            logger.info(
                f"Пользователь {user_id} нажал кнопку 'Добавить время оповещений о приходе'. Действие: проверка лимита и запрос времени.")
            if len(arrival_notification_times) >= 10:
                logger.warning(f"Пользователь {user_id} достиг лимита времени оповещений о приходе (10).")
                await query.message.reply_text(
                    "⏰ Достигнуто максимальное количество оповещений о приходе (10). Удали одно из существующих! 🗑️")
                return ConversationHandler.END
            await query.message.reply_text(
                "⏰ Введи время оповещения о приходе в формате ЧЧ:ММ или Ч:ММ (например, 09:00 или 9:00):")
            logger.info(f"Пользователь {user_id} перешёл в состояние ADD_ARRIVAL_NOTIFICATION")
            return ADD_ARRIVAL_NOTIFICATION

        elif callback_data == 'remove_arrival_notification_time':
            logger.info(
                f"Пользователь {user_id} нажал кнопку 'Удалить время оповещений о приходе'. Действие: отображение списка для удаления.")
            if not arrival_notification_times:
                logger.warning(f"У пользователя {user_id} нет установленных времен оповещений о приходе.")
                await query.message.reply_text("⏰ У тебя нет установленных времен оповещений о приходе! 😕")
                return ConversationHandler.END
            keyboard = [[InlineKeyboardButton(f"{time} 🗑️", callback_data=f"remove_arrival_time_{time}")] for time in
                        arrival_notification_times]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.message.reply_text("⏰ Выбери время оповещения о приходе для удаления: 👇",
                                           reply_markup=reply_markup)

        elif callback_data.startswith('remove_arrival_time_'):
            logger.info(
                f"Пользователь {user_id} нажал кнопку удаления времени оповещения о приходе: {callback_data}. Действие: удаление времени.")
            time_to_remove = callback_data[len('remove_arrival_time_'):]
            if time_to_remove in arrival_notification_times:
                arrival_notification_times.remove(time_to_remove)
                success = update_user_settings(user_id, arrival_notification_times=arrival_notification_times)
                if not success:
                    logger.error(
                        f"Не удалось удалить время оповещения о приходе {time_to_remove} для пользователя {user_id}")
                    await query.message.reply_text("❌ Ошибка при удалении времени оповещения. Попробуй снова.")
                    return ConversationHandler.END

                await query.message.reply_text(f"⏰ Время оповещения о приходе {time_to_remove} удалено! ✅")

                # Обновляем меню после удаления времени
                subscribed, vacation_start, vacation_end, arrival_notification_times, departure_notification_times = get_user_settings(
                    user_id)
                message, reply_markup = create_main_menu(subscribed, vacation_start, vacation_end,
                                                         arrival_notification_times, departure_notification_times)
                await query.message.reply_text(message, reply_markup=reply_markup)

        elif callback_data == 'add_departure_notification_time':
            logger.info(
                f"Пользователь {user_id} нажал кнопку 'Добавить время оповещений об уходе'. Действие: проверка лимита и запрос времени.")
            if len(departure_notification_times) >= 10:
                logger.warning(f"Пользователь {user_id} достиг лимита времени оповещений об уходе (10).")
                await query.message.reply_text(
                    "🚪 Достигнуто максимальное количество оповещений об уходе (10). Удали одно из существующих! 🗑️")
                return ConversationHandler.END
            await query.message.reply_text(
                "🚪 Введи время оповещения об уходе в формате ЧЧ:ММ или Ч:ММ (например, 17:00 или 9:00):")
            logger.info(f"Пользователь {user_id} перешёл в состояние ADD_DEPARTURE_NOTIFICATION")
            return ADD_DEPARTURE_NOTIFICATION

        elif callback_data == 'remove_departure_notification_time':
            logger.info(
                f"Пользователь {user_id} нажал кнопку 'Удалить время оповещений об уходе'. Действие: отображение списка для удаления.")
            if not departure_notification_times:
                logger.warning(f"У пользователя {user_id} нет установленных времен оповещений об уходе.")
                await query.message.reply_text("🚪 У тебя нет установленных времен оповещений об уходе! 😕")
                return ConversationHandler.END
            keyboard = [[InlineKeyboardButton(f"{time} 🗑️", callback_data=f"remove_departure_time_{time}")] for time in
                        departure_notification_times]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.message.reply_text("🚪 Выбери время оповещения об уходе для удаления: 👇",
                                           reply_markup=reply_markup)

        elif callback_data.startswith('remove_departure_time_'):
            logger.info(
                f"Пользователь {user_id} нажал кнопку удаления времени оповещения об уходе: {callback_data}. Действие: удаление времени.")
            time_to_remove = callback_data[len('remove_departure_time_'):]
            if time_to_remove in departure_notification_times:
                departure_notification_times.remove(time_to_remove)
                success = update_user_settings(user_id, departure_notification_times=departure_notification_times)
                if not success:
                    logger.error(
                        f"Не удалось удалить время оповещения об уходе {time_to_remove} для пользователя {user_id}")
                    await query.message.reply_text("❌ Ошибка при удалении времени оповещения. Попробуй снова.")
                    return ConversationHandler.END

                await query.message.reply_text(f"🚪 Время оповещения об уходе {time_to_remove} удалено! ✅")

                # Обновляем меню после удаления времени
                subscribed, vacation_start, vacation_end, arrival_notification_times, departure_notification_times = get_user_settings(
                    user_id)
                message, reply_markup = create_main_menu(subscribed, vacation_start, vacation_end,
                                                         arrival_notification_times, departure_notification_times)
                await query.message.reply_text(message, reply_markup=reply_markup)

        elif callback_data == 'attendance_today':
            logger.info(
                f"Пользователь {user_id} нажал кнопку 'Посещения за сегодня'. Действие: получение данных о посещениях.")
            today = datetime.now().strftime('%Y-%m-%d')
            status = get_attendance(user_id, today)

            # Парсим статус
            start = status.split("Начало: ")[1].split(",")[0].strip()
            end = status.split("Конец: ")[1].split(",")[0].strip() if ", Конец: " in status else \
            status.split("Конец: ")[1].split(",")[0].strip()
            night_shift = status.split("Ночная смена: ")[1].strip()

            # Форматируем время
            start_time = "*не указано*" if start == "не указано" else start.split(" ")[1]
            end_time = "*не указано*" if end == "не указано" else end.split(" ")[1]

            # Формируем сообщение
            message = (
                f"**📅 Посещения за сегодня ({today})**  \n"
                f"⏰ **Начало:** {start_time}  \n"
                f"🏁 **Конец:** {end_time}  \n"
                f"🌙 **Ночная смена:** {night_shift}"
            )
            await query.message.reply_text(message, parse_mode='Markdown')

        elif callback_data == 'attendance_10_days':
            logger.info(
                f"Пользователь {user_id} нажал кнопку 'Посещения за 10 дней'. Действие: получение данных о посещениях за 10 дней.")
            today = datetime.now().strftime('%Y-%m-%d')
            records = get_attendance_last_10_days(user_id, today)
            if not records:
                logger.warning(f"У пользователя {user_id} нет данных о посещениях за последние 10 дней.")
                await query.message.reply_text("📊 Нет данных за последние 10 дней! 😕")
                return ConversationHandler.END

            # Формируем сообщение
            message = "**📊 Посещения за последние 10 дней**  \n"
            for date, status in records:
                # Парсим статус
                start = status.split("Начало: ")[1].split(",")[0].strip()
                end = status.split("Конец: ")[1].split(",")[0].strip() if ", Конец: " in status else \
                status.split("Конец: ")[1].strip()

                # Форматируем время
                start_time = "*не указано*" if start == "не указано" else start.split(" ")[1]
                end_time = "*не указано*" if end == "не указано" else end.split(" ")[1]

                # Добавляем день в сообщение
                message += f"🌟 **{date}**  \n   ⏰ Начало: {start_time}  \n   🏁 Конец: {end_time}  \n\n"

            await query.message.reply_text(message, parse_mode='Markdown')

        return ConversationHandler.END

    except Exception as e:
        logger.error(f"Ошибка в callback_handler для пользователя {user_id}: {str(e)}")
        await query.message.reply_text("❌ Произошла ошибка. Попробуй снова или свяжись с администратором.")
        return ConversationHandler.END


async def set_vacation_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text
    logger.debug(f"Пользователь {user_id} ввёл дату начала отпуска: {text}")

    try:
        # Проверяем формат даты
        vacation_start = datetime.strptime(text, '%d-%m-%Y').strftime('%Y-%m-%d')
        logger.info(f"Дата начала отпуска успешно распарсена: {vacation_start}")
        # Проверяем, что дата не в прошлом
        today = datetime.now().date()
        start_date = datetime.strptime(vacation_start, '%Y-%m-%d').date()
        if start_date < today:
            logger.warning(f"Дата начала отпуска в прошлом: {vacation_start}, текущая дата: {today}")
            await update.message.reply_text(
                "❌ Дата начала отпуска не может быть в прошлом. Попробуй снова (ДД-ММ-ГГГГ, например, 01-01-2025):")
            return SET_VACATION_START
        context.user_data['vacation_start'] = vacation_start
        await update.message.reply_text("📅 Введи дату окончания отпуска в формате ДД-ММ-ГГГГ (например, 01-01-2025):")
        logger.info(f"Пользователь {user_id} перешёл в состояние SET_VACATION_END")
        return SET_VACATION_END

    except ValueError as e:
        logger.error(f"Ошибка парсинга даты начала отпуска для пользователя {user_id}: {str(e)}")
        await update.message.reply_text("❌ Неверный формат даты. Попробуй ещё раз (ДД-ММ-ГГГГ, например, 01-01-2025):")
        return SET_VACATION_START

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
            logger.error(f"Дата начала отпуска не найдена для пользователя {user_id}")
            await update.message.reply_text(
                "❌ Произошла ошибка. Начни заново с помощью кнопки 'Установить период отпуска'. 😕")
            return ConversationHandler.END

        # Проверяем, что дата окончания позже даты начала
        start_date = datetime.strptime(vacation_start, '%Y-%m-%d').date()
        end_date = datetime.strptime(vacation_end, '%Y-%m-%d').date()
        if end_date <= start_date:
            logger.warning(
                f"Дата окончания ({vacation_end}) не позже даты начала ({vacation_start}) для пользователя {user_id}")
            await update.message.reply_text(
                "❌ Дата окончания отпуска должна быть позже даты начала. Попробуй ещё раз (ДД-ММ-ГГГГ):")
            return SET_VACATION_END

        success = update_user_settings(user_id, vacation_start=vacation_start, vacation_end=vacation_end)
        if not success:
            logger.error(f"Не удалось установить период отпуска для пользователя {user_id}")
            await update.message.reply_text("❌ Ошибка при установке периода отпуска. Попробуй снова.")
            return ConversationHandler.END

        logger.info(f"Период отпуска для пользователя {user_id} успешно установлен: {vacation_start} - {vacation_end}")

        subscribed, vacation_start, vacation_end, arrival_notification_times, departure_notification_times = get_user_settings(
            user_id)
        message, reply_markup = create_main_menu(subscribed, vacation_start, vacation_end, arrival_notification_times,
                                                 departure_notification_times)
        message = (
            f"🏖️ Период отпуска {vacation_start} - {vacation_end} установлен! ✅\n\n"
            f"{message}"
        )
        await update.message.reply_text(message, reply_markup=reply_markup)
        return ConversationHandler.END

    except ValueError as e:
        logger.error(f"Ошибка парсинга даты окончания отпуска для пользователя {user_id}: {str(e)}")
        await update.message.reply_text("❌ Неверный формат даты. Попробуй ещё раз (ДД-ММ-ГГГГ, например, 01-01-2025):")
        return SET_VACATION_END

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
            await update.message.reply_text(
                "❌ Неверный формат времени. Попробуй ещё раз (ЧЧ:ММ или Ч:ММ, например, 09:00 или 9:00):")
            return ADD_ARRIVAL_NOTIFICATION

        # Нормализуем время в формат ЧЧ:ММ
        parts = text.split(':')
        hours = int(parts[0])
        minutes = int(parts[1])
        if hours < 0 or hours > 23 or minutes < 0 or minutes > 59:
            raise ValueError("Часы должны быть от 0 до 23, минуты от 00 до 59")
        time_str = f"{hours:02d}:{minutes:02d}"
        logger.info(f"Время оповещения о приходе успешно нормализовано: {time_str}")

        subscribed, vacation_start, vacation_end, arrival_notification_times, departure_notification_times = get_user_settings(
            user_id)
        if time_str in arrival_notification_times:
            await update.message.reply_text(f"⏰ Время оповещения о приходе {time_str} уже добавлено! 😕")
            return ConversationHandler.END

        arrival_notification_times.append(time_str)
        success = update_user_settings(user_id, arrival_notification_times=arrival_notification_times)
        if not success:
            logger.error(f"Не удалось обновить время оповещения о приходе для пользователя {user_id}")
            await update.message.reply_text("❌ Ошибка при добавлении времени оповещения. Попробуй снова.")
            return ConversationHandler.END

        logger.info(f"Время оповещения о приходе {time_str} успешно добавлено для пользователя {user_id}")

        subscribed, vacation_start, vacation_end, arrival_notification_times, departure_notification_times = get_user_settings(
            user_id)
        message, reply_markup = create_main_menu(subscribed, vacation_start, vacation_end, arrival_notification_times,
                                                 departure_notification_times)
        message = (
            f"⏰ Время оповещения о приходе {time_str} добавлено! ✅\n\n"
            f"{message}"
        )
        await update.message.reply_text(message, reply_markup=reply_markup)
        return ConversationHandler.END

    except ValueError as e:
        logger.error(f"Ошибка обработки времени оповещения о приходе для пользователя {user_id}: {str(e)}")
        await update.message.reply_text(
            "❌ Неверный формат времени. Попробуй ещё раз (ЧЧ:ММ или Ч:ММ, например, 09:00 или 9:00):")
        return ADD_ARRIVAL_NOTIFICATION

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
            await update.message.reply_text(
                "❌ Неверный формат времени. Попробуй ещё раз (ЧЧ:ММ или Ч:ММ, например, 17:00 или 9:00):")
            return ADD_DEPARTURE_NOTIFICATION

        # Нормализуем время в формат ЧЧ:ММ
        parts = text.split(':')
        hours = int(parts[0])
        minutes = int(parts[1])
        if hours < 0 or hours > 23 or minutes < 0 or minutes > 59:
            raise ValueError("Часы должны быть от 0 до 23, минуты от 00 до 59")
        time_str = f"{hours:02d}:{minutes:02d}"
        logger.info(f"Время оповещения об уходе успешно нормализовано: {time_str}")

        subscribed, vacation_start, vacation_end, arrival_notification_times, departure_notification_times = get_user_settings(
            user_id)
        if time_str in departure_notification_times:
            await update.message.reply_text(f"🚪 Время оповещения об уходе {time_str} уже добавлено! 😕")
            return ConversationHandler.END

        departure_notification_times.append(time_str)
        success = update_user_settings(user_id, departure_notification_times=departure_notification_times)
        if not success:
            logger.error(f"Не удалось обновить время оповещения об уходе для пользователя {user_id}")
            await update.message.reply_text("❌ Ошибка при добавлении времени оповещения. Попробуй снова.")
            return ConversationHandler.END

        logger.info(f"Время оповещения об уходе {time_str} успешно добавлено для пользователя {user_id}")

        subscribed, vacation_start, vacation_end, arrival_notification_times, departure_notification_times = get_user_settings(
            user_id)
        message, reply_markup = create_main_menu(subscribed, vacation_start, vacation_end, arrival_notification_times,
                                                 departure_notification_times)
        message = (
            f"🚪 Время оповещения об уходе {time_str} добавлено! ✅\n\n"
            f"{message}"
        )
        await update.message.reply_text(message, reply_markup=reply_markup)
        return ConversationHandler.END

    except ValueError as e:
        logger.error(f"Ошибка обработки времени оповещения об уходе для пользователя {user_id}: {str(e)}")
        await update.message.reply_text(
            "❌ Неверный формат времени. Попробуй ещё раз (ЧЧ:ММ или Ч:ММ, например, 17:00 или 9:00):")
        return ADD_DEPARTURE_NOTIFICATION

    except Exception as e:
        logger.error(f"Неожиданная ошибка в add_departure_notification_time для пользователя {user_id}: {str(e)}")
        await update.message.reply_text("❌ Произошла ошибка. Попробуй снова или свяжись с администратором.")
        return ConversationHandler.END