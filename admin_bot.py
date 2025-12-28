# admin_bot.py

import os
import re
import logging
import asyncio
from typing import Dict

from telethon import events, Button, TelegramClient
from telethon.errors.rpcerrorlist import (
    MessageNotModifiedError, 
    SessionPasswordNeededError,
    PhoneCodeInvalidError,
    PasswordHashInvalidError
)

from config import ADMIN_IDS, SESSIONS_DIR, API_ID, API_HASH
from db import (
    get_global_stats,
    get_latest_errors,
    get_accounts,
    toggle_account_active,
    update_proxy,
    add_account,
    get_account_by_id,
    delete_account,
)
from scheduler import start_scheduler, stop_scheduler, is_scheduler_running

logger = logging.getLogger(__name__)

# Simple in-memory state for admin flows
ADMIN_STATE: Dict[int, Dict] = {}


def _ensure_sessions_dir():
    if not os.path.exists(SESSIONS_DIR):
        os.makedirs(SESSIONS_DIR, exist_ok=True)


def setup_admin_handlers(bot):
    
    async def show_accounts_page(event, page: int = 1):
        """Show accounts list with pagination (5x2 grid)."""
        accounts = await get_accounts(active_only=False)
        total = len(accounts)

        PAGE_SIZE_GRID = 10 # 5 rows * 2 columns

        if total == 0:
            text = "No accounts stored yet."
            if event.is_callback:
                await event.edit(text)
            else:
                await event.respond(text)
            return

        total_pages = (total + PAGE_SIZE_GRID - 1) // PAGE_SIZE_GRID
        if page < 1: page = 1
        if page > total_pages: page = total_pages

        start_idx = (page - 1) * PAGE_SIZE_GRID
        end_idx = start_idx + PAGE_SIZE_GRID
        page_accounts = accounts[start_idx:end_idx]

        text = f"📂 Accounts (page {page}/{total_pages}):"
        btn_rows = []
        
        # Create 5 rows of 2 columns
        for i in range(0, len(page_accounts), 2):
            row = []
            for acc in page_accounts[i:i+2]:
                acc_id = acc["id"]
                label = acc["label"] or f"Acc {acc_id}"
                status_emoji = "🟢" if acc["is_active"] else "🔴"
                row.append(Button.inline(f"{status_emoji} {label}", data=f"accounts:view:{acc_id}:{page}"))
            btn_rows.append(row)

        # Pagination buttons
        nav_buttons = []
        if page > 1:
            nav_buttons.append(Button.inline("◀️ Prev", data=f"menu:accounts:{page-1}"))
        if page < total_pages:
            nav_buttons.append(Button.inline("Next ▶️", data=f"menu:accounts:{page+1}"))
        if nav_buttons:
            btn_rows.append(nav_buttons)

        if event.is_callback:
            await event.edit(text, buttons=btn_rows)
        else:
            await event.respond(text, buttons=btn_rows)

    @bot.on(events.NewMessage(pattern="/start"))
    async def start_handler(event):
        if event.sender_id not in ADMIN_IDS:
            await event.reply("Access denied.")
            return
        await show_main_menu(event)

    async def show_main_menu(event):
        text = "🛠 Admin Panel\nChoose an action:"
        buttons = [
            ["📂 Accounts", "📊 Stats"],
            ["⚠️ Errors", "⏱ Scheduler"],
            ["➕ Add Account"]
        ]
        await event.respond(text, buttons=buttons)

    @bot.on(events.NewMessage(func=lambda e: e.text == "📂 Accounts"))
    async def msg_accounts(event):
        if event.sender_id not in ADMIN_IDS: return
        await show_accounts_page(event, page=1)

    @bot.on(events.NewMessage(func=lambda e: e.text == "📊 Stats"))
    async def msg_stats(event):
        if event.sender_id not in ADMIN_IDS: return
        stats = await get_global_stats()
        text_lines = [
            "📊 Global Stats",
            f"Total accounts: {stats['total_accounts']}",
            f"Active accounts: {stats['active_accounts']}",
            f"Total groups created (all accounts): {stats['total_groups']}",
        ]
        await event.respond("\n".join(text_lines))

    @bot.on(events.NewMessage(func=lambda e: e.text == "⚠️ Errors"))
    async def msg_errors(event):
        if event.sender_id not in ADMIN_IDS: return
        errors = await get_latest_errors(10)
        if not errors:
            text = "No errors logged yet."
        else:
            lines = ["⚠️ Latest Errors:"]
            for err in errors:
                acc_id = err["account_id"]
                context = err["context"]
                created_at = err["created_at"]
                snippet = (err["error_text"] or "")[:200]
                lines.append(
                    f"[{created_at}] Account={acc_id} | {context}\n{snippet}\n"
                )
            text = "\n".join(lines)
        await event.respond(text)

    @bot.on(events.NewMessage(func=lambda e: e.text == "⏱ Scheduler"))
    async def msg_scheduler(event):
        if event.sender_id not in ADMIN_IDS: return
        running = is_scheduler_running()
        status = "🟢 Running" if running else "🔴 Stopped"
        text = f"⏱ Scheduler Status: {status}"
        buttons = [
            [
                Button.inline("▶️ Start", data=b"scheduler:start"),
                Button.inline("⏹ Stop", data=b"scheduler:stop"),
            ]
        ]
        await event.respond(text, buttons=buttons)

    @bot.on(events.NewMessage(func=lambda e: e.text == "➕ Add Account"))
    async def msg_add_account(event):
        if event.sender_id not in ADMIN_IDS: return
        ADMIN_STATE[event.sender_id] = {"mode": "add_account_phone"}
        await event.respond("Please enter the phone number (including country code, e.g., +989123456789):")

    @bot.on(events.CallbackQuery(pattern=re.compile(br"menu:accounts:(\d+)")))
    async def cb_menu_accounts_page(event):
        if event.sender_id not in ADMIN_IDS: return
        page = int(event.pattern_match.group(1))
        await show_accounts_page(event, page=page)

    @bot.on(events.CallbackQuery(pattern=re.compile(br"accounts:view:(\d+):(\d+)")))
    async def cb_account_view(event):
        if event.sender_id not in ADMIN_IDS: return
        acc_id = int(event.pattern_match.group(1))
        page = int(event.pattern_match.group(2))
        acc = await get_account_by_id(acc_id)
        if not acc:
            await event.answer("Account not found.", alert=True)
            return
        
        status = "Active 🟢" if acc["is_active"] else "Inactive 🔴"
        text = (
            f"👤 Account: {acc['label']}\n"
            f"ID: {acc_id}\n"
            f"Status: {status}\n"
            f"Groups Created: {acc['created_groups_count']}\n"
            f"Proxy: {acc['proxy_host'] or 'None'}"
        )
        
        buttons = [
            [
                Button.inline("Turn Off" if acc["is_active"] else "Turn On", data=f"accounts:toggle:{acc_id}:{page}"),
                Button.inline("Set Proxy", data=f"accounts:proxy:{acc_id}:{page}")
            ],
            [
                Button.inline("Delete Account", data=f"accounts:delete_confirm:{acc_id}:{page}"),
                Button.inline("Send Session File", data=f"accounts:send_session:{acc_id}")
            ],
            [Button.inline("⬅️ Back to list", data=f"menu:accounts:{page}")]
        ]
        await event.edit(text, buttons=buttons)

    @bot.on(events.CallbackQuery(pattern=re.compile(br"accounts:toggle:(\d+):(\d+)")))
    async def cb_accounts_toggle(event):
        if event.sender_id not in ADMIN_IDS: return
        acc_id = int(event.pattern_match.group(1))
        page = int(event.pattern_match.group(2))
        await toggle_account_active(acc_id)
        await cb_account_view(event)

    @bot.on(events.CallbackQuery(pattern=re.compile(br"accounts:proxy:(\d+):(\d+)")))
    async def cb_accounts_proxy(event):
        if event.sender_id not in ADMIN_IDS: return
        acc_id = int(event.pattern_match.group(1))
        ADMIN_STATE[event.sender_id] = {"mode": "setting_proxy", "account_id": acc_id}
        await event.respond(
            f"🌐 Proxy for account {acc_id}\n"
            "Format: `host:port` or `host:port:user:pass`\n"
            "Send `none` to clear."
        )

    @bot.on(events.CallbackQuery(pattern=re.compile(br"accounts:delete_confirm:(\d+):(\d+)")))
    async def cb_delete_confirm(event):
        if event.sender_id not in ADMIN_IDS: return
        acc_id = int(event.pattern_match.group(1))
        page = int(event.pattern_match.group(2))
        buttons = [
            [Button.inline("✅ Yes, Delete", data=f"accounts:delete:{acc_id}:{page}")],
            [Button.inline("❌ No, Cancel", data=f"accounts:view:{acc_id}:{page}")]
        ]
        await event.edit("Are you sure you want to delete this account?", buttons=buttons)

    @bot.on(events.CallbackQuery(pattern=re.compile(br"accounts:delete:(\d+):(\d+)")))
    async def cb_delete(event):
        if event.sender_id not in ADMIN_IDS: return
        acc_id = int(event.pattern_match.group(1))
        page = int(event.pattern_match.group(2))
        await delete_account(acc_id)
        await event.answer("Account deleted.")
        await show_accounts_page(event, page=page)

    @bot.on(events.CallbackQuery(pattern=re.compile(br"accounts:send_session:(\d+)")))
    async def cb_send_session(event):
        if event.sender_id not in ADMIN_IDS: return
        acc_id = int(event.pattern_match.group(1))
        acc = await get_account_by_id(acc_id)
        if acc:
            path = os.path.join(SESSIONS_DIR, acc["session_path"])
            if not path.endswith(".session"):
                path += ".session"
            if os.path.exists(path):
                await event.respond(f"Session file for {acc['label']}:", file=path)
            else:
                await event.answer("File not found.", alert=True)

    @bot.on(events.CallbackQuery(pattern=b"scheduler:start"))
    async def cb_scheduler_start(event):
        if event.sender_id not in ADMIN_IDS: return
        start_scheduler()
        await event.answer("Scheduler started.", alert=True)
        # Refresh scheduler msg
        running = is_scheduler_running()
        status = "🟢 Running" if running else "🔴 Stopped"
        text = f"⏱ Scheduler Status: {status}"
        buttons = [[Button.inline("▶️ Start", data=b"scheduler:start"), Button.inline("⏹ Stop", data=b"scheduler:stop")]]
        await event.edit(text, buttons=buttons)

    @bot.on(events.CallbackQuery(pattern=b"scheduler:stop"))
    async def cb_scheduler_stop(event):
        if event.sender_id not in ADMIN_IDS: return
        stop_scheduler()
        await event.answer("Scheduler stopped.", alert=True)
        # Refresh scheduler msg
        running = is_scheduler_running()
        status = "🟢 Running" if running else "🔴 Stopped"
        text = f"⏱ Scheduler Status: {status}"
        buttons = [[Button.inline("▶️ Start", data=b"scheduler:start"), Button.inline("⏹ Stop", data=b"scheduler:stop")]]
        await event.edit(text, buttons=buttons)

    @bot.on(events.NewMessage)
    async def admin_message_handler(event):
        if event.sender_id not in ADMIN_IDS: return
        if not event.text: return
        
        state = ADMIN_STATE.get(event.sender_id)
        if not state: return
        
        mode = state.get("mode")
        text = event.text.strip()
        
        if mode == "add_account_phone":
            phone = text
            client = TelegramClient(os.path.join(SESSIONS_DIR, f"{phone}"), API_ID, API_HASH)
            await client.connect()
            try:
                sent_code = await client.send_code_request(phone)
                ADMIN_STATE[event.sender_id] = {
                    "mode": "add_account_code",
                    "phone": phone,
                    "phone_code_hash": sent_code.phone_code_hash,
                    "client": client
                }
                await event.respond(f"Code sent to {phone}. Please enter the code:")
            except Exception as e:
                await event.respond(f"Error: {e}")
                await client.disconnect()
                ADMIN_STATE.pop(event.sender_id)

        elif mode == "add_account_code":
            code = text
            phone = state["phone"]
            phone_code_hash = state["phone_code_hash"]
            client = state["client"]
            try:
                await client.sign_in(phone, code, phone_code_hash=phone_code_hash)
                # Success
                await add_account(label=phone, session_path=f"{phone}")
                await event.respond(f"✅ Account {phone} added successfully!")
                await client.disconnect()
                ADMIN_STATE.pop(event.sender_id)
            except SessionPasswordNeededError:
                ADMIN_STATE[event.sender_id]["mode"] = "add_account_2fa"
                await event.respond("Two-step verification enabled. Please enter your password:")
            except PhoneCodeInvalidError:
                await event.respond("Invalid code. Please try again:")
            except Exception as e:
                await event.respond(f"Error: {e}")
                await client.disconnect()
                ADMIN_STATE.pop(event.sender_id)

        elif mode == "add_account_2fa":
            password = text
            client = state["client"]
            try:
                await client.sign_in(password=password)
                phone = state["phone"]
                await add_account(label=phone, session_path=f"{phone}")
                await event.respond(f"✅ Account {phone} added successfully!")
                await client.disconnect()
                ADMIN_STATE.pop(event.sender_id)
            except PasswordHashInvalidError:
                await event.respond("Invalid password. Please try again:")
            except Exception as e:
                await event.respond(f"Error: {e}")
                await client.disconnect()
                ADMIN_STATE.pop(event.sender_id)

        elif mode == "setting_proxy":
            acc_id = state["account_id"]
            if text.lower() == "none":
                await update_proxy(acc_id, None, None, None, None)
                await event.respond(f"✅ Proxy cleared for account {acc_id}.")
            else:
                parts = text.split(":")
                if len(parts) in (2, 4):
                    host = parts[0]
                    try:
                        port = int(parts[1])
                        user = parts[2] if len(parts) == 4 else None
                        pw = parts[3] if len(parts) == 4 else None
                        await update_proxy(acc_id, host, port, user, pw)
                        await event.respond(f"✅ Proxy updated for account {acc_id}.")
                    except ValueError:
                        await event.respond("Invalid port.")
                else:
                    await event.respond("Invalid format. Use `host:port` or `host:port:user:pass`.")
            ADMIN_STATE.pop(event.sender_id)
