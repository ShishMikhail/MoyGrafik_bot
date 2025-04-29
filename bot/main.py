from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ConversationHandler
from bot.handlers import start, menu, status, callback_handler, set_vacation_start, set_vacation_end, add_arrival_notification_time, add_departure_notification_time
from bot.registration import register
from bot.scheduler import setup_scheduler
from bot.utils import INPUT_VACATION_START, INPUT_VACATION_END, INPUT_ARRIVAL_NOTIFICATION_TIME, INPUT_DEPARTURE_NOTIFICATION_TIME

app = ApplicationBuilder().token("7437055328:AAHgZeBAUu-fLz90H9prMWFg-1mz2z0qzrg").build()

# Настройка планировщика уведомлений
setup_scheduler(app)

# Обработчики команд
app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("menu", menu))
app.add_handler(CommandHandler("status", status))
app.add_handler(CommandHandler("register", register))

# Обработчик кнопок и состояний
conv_handler = ConversationHandler(
    entry_points=[CallbackQueryHandler(callback_handler)],
    states={
        INPUT_VACATION_START: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_vacation_start)],
        INPUT_VACATION_END: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_vacation_end)],
        INPUT_ARRIVAL_NOTIFICATION_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_arrival_notification_time)],
        INPUT_DEPARTURE_NOTIFICATION_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_departure_notification_time)],
    },
    fallbacks=[],
)
app.add_handler(conv_handler)

# Запуск бота
app.run_polling()