import asyncio
import logging
import os

from telethon import TelegramClient

from config import API_ID, API_HASH, BOT_TOKEN
from db import init_db
from admin_bot import setup_admin_handlers
from scheduler import run_scheduler

# Basic logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
)


async def main():
    await init_db()

    bot = TelegramClient("admin_bot", API_ID, API_HASH)
    await bot.start(bot_token=BOT_TOKEN)

    setup_admin_handlers(bot)

    # Start scheduler in background
    asyncio.create_task(run_scheduler(bot))

    print("🤖 Admin bot started. Scheduler running in background.")
    await bot.run_until_disconnected()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("Shutting down...")
