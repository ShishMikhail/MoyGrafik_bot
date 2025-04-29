from datetime import datetime
import pytz

# Состояния для ConversationHandler
INPUT_VACATION_START = 0
INPUT_VACATION_END = 1
INPUT_ARRIVAL_NOTIFICATION_TIME = 2
INPUT_DEPARTURE_NOTIFICATION_TIME = 3
INPUT_CLID = 4  # Новое состояние для ввода CLID

# Определяем состояния для ConversationHandler
SET_VACATION_START, SET_VACATION_END, ADD_ARRIVAL_NOTIFICATION, ADD_DEPARTURE_NOTIFICATION, INPUT_CLID_STATE = range(INPUT_VACATION_START, INPUT_CLID + 1)

VLADIVOSTOK_TZ = pytz.timezone('Asia/Vladivostok')

