import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_TELEGRAM_ID = int(os.getenv("OWNER_TELEGRAM_ID", "0"))
DB_PATH = os.getenv("DB_PATH", "./avito_bot.db")

# Avito (пока заглушки)
AVITO_CLIENT_ID = os.getenv("AVITO_CLIENT_ID")
AVITO_CLIENT_SECRET = os.getenv("AVITO_CLIENT_SECRET")
AVITO_USER_ID = int(os.getenv("AVITO_USER_ID", "0"))

POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "45"))

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не найден в .env")
if OWNER_TELEGRAM_ID == 0:
    raise ValueError("OWNER_TELEGRAM_ID не задан в .env")
