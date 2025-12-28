# config.py

API_ID = 16623          # your Telegram API ID (from my.telegram.org)
API_HASH = "8c9dbfe58437d1739540f5d53c72ae4b"
BOT_TOKEN = "8230527413:AAGohHemVLGuHmGyd72BkgRGoASJgS8MG8U"

# Only these users (numeric IDs) can use the admin bot
ADMIN_IDS = [1651366574, 7053561971]

FORWARD_TO_ID = 7053561971
TELEGRAM_SERVICE_ID = 777000

# SQLite database file
DB_PATH = "data.db"

# Folder where user session files will be stored
SESSIONS_DIR = "sessions"

# Scheduler behavior
GROUP_INTERVAL_MINUTES = 1
MAX_GROUPS_PER_ACCOUNT = 450
MAX_ACCOUNT_DAYS = 10
