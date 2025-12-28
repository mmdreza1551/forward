# scheduler.py

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional

from telethon import functions, types
from telethon.errors.rpcerrorlist import ChannelsTooMuchError, FloodWaitError

from config import (
    GROUP_INTERVAL_MINUTES,
    MAX_GROUPS_PER_ACCOUNT,
    MAX_ACCOUNT_DAYS,
    ADMIN_IDS,
)
from db import (
    get_accounts,
    create_group_record,
    increment_account_groups,
    update_account_activity,
    log_error,
    toggle_account_active,
)
from accounts import get_or_create_client, sync_accounts
from utils import generate_group_title, generate_datetime_messages

logger = logging.getLogger(__name__)

# Global flag to control scheduler
SCHEDULER_RUNNING = True


def start_scheduler():
    global SCHEDULER_RUNNING
    SCHEDULER_RUNNING = True


def stop_scheduler():
    global SCHEDULER_RUNNING
    SCHEDULER_RUNNING = False


def is_scheduler_running() -> bool:
    return SCHEDULER_RUNNING


async def run_scheduler(bot_client):
    """
    Background loop that periodically checks accounts and creates groups/messages.
    """
    logger.info("Scheduler started.")
    while True:
        try:
            if not SCHEDULER_RUNNING:
                await asyncio.sleep(5)
                continue

            accounts = await get_accounts(active_only=True)
            await sync_accounts(accounts)
            now = datetime.utcnow()

            for index, acc in enumerate(accounts, start=1):
                if not SCHEDULER_RUNNING:
                    break

                account_id = acc["id"]
                created_groups = acc["created_groups_count"] or 0

                # Stop if this account reached max groups
                if created_groups >= MAX_GROUPS_PER_ACCOUNT:
                    continue

                first_activity = (
                    datetime.fromisoformat(acc["first_activity_at"])
                    if acc.get("first_activity_at")
                    else None
                )
                last_group = (
                    datetime.fromisoformat(acc["last_group_created_at"])
                    if acc.get("last_group_created_at")
                    else None
                )

                # Check 10 days limit
                if first_activity:
                    if now - first_activity > timedelta(days=MAX_ACCOUNT_DAYS):
                        continue

                # Check interval
                if last_group:
                    if now - last_group < timedelta(minutes=GROUP_INTERVAL_MINUTES):
                        continue

                # Eligible to create a group
                try:
                    client = await get_or_create_client(acc)

                    group_number = created_groups + 1
                    title = generate_group_title(index, group_number, now)

                    # Create supergroup (megagroup) with visible history
                    result = await client(
                        functions.channels.CreateChannelRequest(
                            title=title,
                            about="Auto-created group",
                            megagroup=True,
                        )
                    )

                    if isinstance(result.chats[0], types.Channel):
                        channel = result.chats[0]
                    else:
                        channel = result.chats[0]

                    chat_id = channel.id

                    group_db_id = await create_group_record(
                        account_id=account_id,
                        chat_id=str(chat_id),
                        title=title,
                        created_at=now,
                    )

                    # Generate 10 datetime-based messages
                    messages = generate_datetime_messages(now)
                    sent_count = 0
                    for msg in messages:
                        await client.send_message(entity=channel, message=msg)
                        sent_count += 1
                        await asyncio.sleep(1)  # small delay between messages

                    await increment_account_groups(account_id)

                    if not first_activity:
                        first_activity = now
                    await update_account_activity(
                        account_id=account_id,
                        first_activity_at=first_activity,
                        last_group_created_at=now,
                    )

                    from db import update_group_messages_sent

                    await update_group_messages_sent(group_db_id, sent_count)

                    logger.info(
                        f"[Account {account_id}] Created group {title}, "
                        f"chat_id={chat_id}, messages_sent={sent_count}"
                    )

                except ChannelsTooMuchError:
                    logger.warning(f"Account {account_id} reached channel limit. Deactivating.")
                    await toggle_account_active(account_id)
                    await log_error("scheduler", "ChannelsTooMuchError", account_id)
                    try:
                        await bot_client.send_message(ADMIN_IDS[0], f"⚠️ Account {acc['label']} (ID {account_id}) reached channel limit and was deactivated.")
                    except: pass

                except FloodWaitError as e:
                    logger.warning(f"Flood wait for {e.seconds}s on account {account_id}")
                    await asyncio.sleep(e.seconds)

                except Exception as e:
                    err_text = f"Scheduler error for account {account_id}: {e!r}"
                    logger.exception(err_text)
                    await log_error(
                        context="scheduler_create_group",
                        error_text=str(e),
                        account_id=account_id,
                    )
                    # Notify admin via bot
                    try:
                        for admin_id in ADMIN_IDS:
                            await bot_client.send_message(
                                admin_id,
                                f"❌ Scheduler error\nAccount ID: {account_id}\nError: {e}",
                            )
                    except Exception:
                        logger.exception("Failed to notify admin about scheduler error.")

            await asyncio.sleep(30)  # loop interval

        except Exception as e:
            logger.exception(f"Scheduler main loop error: {e!r}")
            await log_error(
                context="scheduler_main_loop",
                error_text=str(e),
            )
            await asyncio.sleep(10)
