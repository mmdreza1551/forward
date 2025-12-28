# admin_bot.py

import os
import re
import logging
from typing import Dict

from telethon import events, Button
from telethon.errors.rpcerrorlist import MessageNotModifiedError

from config import ADMIN_ID, SESSIONS_DIR
from db import (
    get_global_stats,
    get_latest_errors,
    get_accounts,
    toggle_account_active,
    update_proxy,
    add_account,
)
from scheduler import start_scheduler, stop_scheduler, is_scheduler_running

PAGE_SIZE = 5  # number of accounts per page in Accounts menu
logger = logging.getLogger(__name__)

# Simple in-memory state for admin flows
ADMIN_STATE: Dict[int, Dict] = {}


def _ensure_sessions_dir():
    if not os.path.exists(SESSIONS_DIR):
        os.makedirs(SESSIONS_DIR, exist_ok=True)


def setup_admin_handlers(bot):
    async def show_accounts_page(event, page: int = 1):
        """Show accounts list with pagination (5 accounts per page)."""
        accounts = await get_accounts(active_only=False)
        total = len(accounts)

        if total == 0:
            text = "No accounts stored yet."
            buttons = [
                [Button.inline("➕ Add Account", data=b"accounts:add")],
                [Button.inline("⬅️ Back", data=b"menu:back")],
            ]
            await event.edit(text, buttons=buttons)
            return

        # calc total pages
        total_pages = (total + PAGE_SIZE - 1) // PAGE_SIZE
        if page < 1:
            page = 1
        if page > total_pages:
            page = total_pages

        start_idx = (page - 1) * PAGE_SIZE
        end_idx = start_idx + PAGE_SIZE
        page_accounts = accounts[start_idx:end_idx]

        lines = [f"📂 Accounts (page {page}/{total_pages}):", ""]
        btn_rows = []

        for acc in page_accounts:
            acc_id = acc["id"]
            label = acc["label"] or f"Account {acc_id}"
            cg = acc["created_groups_count"] or 0
            active = "✅" if acc["is_active"] else "❌"
            proxy = "🌐" if acc["proxy_host"] else "🚫"
            lines.append(
                f"ID {acc_id}: {label} | Groups: {cg} | Active: {active} | Proxy: {proxy}"
            )
            btn_rows.append(
                [
                    Button.inline(
                        f"Toggle {acc_id}",
                        data=f"accounts:toggle:{acc_id}:{page}".encode(),
                    ),
                    Button.inline(
                        f"Proxy {acc_id}",
                        data=f"accounts:proxy:{acc_id}:{page}".encode(),
                    ),
                ]
            )


        # Add account button
        btn_rows.append([Button.inline("➕ Add Account", data=b"accounts:add")])

        # Pagination buttons
        nav_buttons = []
        if page > 1:
            nav_buttons.append(
                Button.inline(
                    "◀️ Prev", data=f"menu:accounts:{page-1}".encode()
                )
            )
        if page < total_pages:
            nav_buttons.append(
                Button.inline(
                    "Next ▶️", data=f"menu:accounts:{page+1}".encode()
                )
            )
        if nav_buttons:
            btn_rows.append(nav_buttons)

        # Back button
        btn_rows.append([Button.inline("⬅️ Back", data=b"menu:back")])

        await event.edit("\n".join(lines), buttons=btn_rows)

    @bot.on(events.NewMessage(pattern="/start"))
    async def start_handler(event):
        if event.sender_id != ADMIN_ID:
            await event.reply("Access denied.")
            return

        await show_main_menu(event)

    async def show_main_menu(event):
        text = "🛠 Admin Panel\nChoose an action:"
        buttons = [
            [
                Button.inline("📂 Accounts", data=b"menu:accounts"),
                Button.inline("📊 Global Stats", data=b"menu:stats"),
            ],
            [
                Button.inline("⚠️ Errors", data=b"menu:errors"),
                Button.inline("⏱ Scheduler", data=b"menu:scheduler"),
            ],
        ]
        await event.respond(text, buttons=buttons)

    @bot.on(events.CallbackQuery(pattern=b"menu:accounts"))
    async def cb_menu_accounts(event):
        if event.sender_id != ADMIN_ID:
            await event.answer("Access denied.", alert=True)
            return

        # always open page 1
        await show_accounts_page(event, page=1)

    @bot.on(events.CallbackQuery(pattern=re.compile(br"menu:accounts:(\d+)")))
    async def cb_menu_accounts_page(event):
        if event.sender_id != ADMIN_ID:
            await event.answer("Access denied.", alert=True)
            return

        m = re.match(br"menu:accounts:(\d+)", event.data)
        if not m:
            await event.answer("Invalid page.", alert=True)
            return

        page = int(m.group(1))
        await show_accounts_page(event, page=page)

    @bot.on(events.CallbackQuery(pattern=b"menu:stats"))
    async def cb_menu_stats(event):
        if event.sender_id != ADMIN_ID:
            await event.answer("Access denied.", alert=True)
            return

        stats = await get_global_stats()
        text_lines = [
            "📊 Global Stats",
            f"Total accounts: {stats['total_accounts']}",
            f"Active accounts: {stats['active_accounts']}",
            f"Total groups created (all accounts): {stats['total_groups']}",
            "",
            "Per-account:",
        ]
        for acc in stats["accounts"]:
            active = "✅" if acc["is_active"] else "❌"
            proxy = "🌐" if acc["proxy_host"] else "🚫"
            text_lines.append(
                f"ID {acc['id']}: {acc['label']} | Groups: {acc['created_groups_count']} | {active} | {proxy}"
            )

        buttons = [[Button.inline("⬅️ Back", data=b"menu:back")]]
        await event.edit("\n".join(text_lines), buttons=buttons)

    @bot.on(events.CallbackQuery(pattern=b"menu:errors"))
    async def cb_menu_errors(event):
        if event.sender_id != ADMIN_ID:
            await event.answer("Access denied.", alert=True)
            return

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

        buttons = [[Button.inline("⬅️ Back", data=b"menu:back")]]
        await event.edit(text, buttons=buttons)

    @bot.on(events.CallbackQuery(pattern=b"menu:scheduler"))
    async def cb_menu_scheduler(event):
        if event.sender_id != ADMIN_ID:
            await event.answer("Access denied.", alert=True)
            return

        running = is_scheduler_running()
        status = "🟢 Running" if running else "🔴 Stopped"
        text = f"⏱ Scheduler Status: {status}"
        buttons = [
            [
                Button.inline("▶️ Start", data=b"scheduler:start"),
                Button.inline("⏹ Stop", data=b"scheduler:stop"),
            ],
            [Button.inline("⬅️ Back", data=b"menu:back")],
        ]

        try:
            await event.edit(text, buttons=buttons)
        except MessageNotModifiedError:
            # Message content & buttons are the same as before → ignore
            pass

    @bot.on(events.CallbackQuery(pattern=b"menu:back"))
    async def cb_menu_back(event):
        if event.sender_id != ADMIN_ID:
            await event.answer("Access denied.", alert=True)
            return
        # simulate /start
        await event.delete()
        fake = event
        await start_handler(fake)

    @bot.on(events.CallbackQuery(pattern=b"accounts:add"))
    async def cb_accounts_add(event):
        if event.sender_id != ADMIN_ID:
            await event.answer("Access denied.", alert=True)
            return

        _ensure_sessions_dir()
        ADMIN_STATE[event.sender_id] = {"mode": "adding_account_wait_file"}
        text = (
            "➕ Add Account\n\n"
            "Please send a session file (`.session`) for this account.\n"
            "The file name will be used as the label (without extension)."
        )
        await event.edit(text, buttons=[[Button.inline("⬅️ Back", data=b"menu:accounts")]])

    @bot.on(events.NewMessage)
    async def admin_message_handler(event):
        # فقط ادمین
        if event.sender_id != ADMIN_ID:
            return

        state = ADMIN_STATE.get(event.sender_id)
        text = (event.raw_text or "").strip()

        # حالت اضافه‌کردن اکانت (انتظار فایل سشن)
        if state and state.get("mode") == "adding_account_wait_file":
            if event.document:
                file_name = event.file.name or "session.session"
                if not file_name.endswith(".session"):
                    await event.reply("File must be a .session file.")
                    return

                _ensure_sessions_dir()
                path = os.path.join(SESSIONS_DIR, file_name)

                await event.download_media(file=path)

                label = os.path.splitext(file_name)[0]
                await add_account(label=label, session_path=file_name)

                ADMIN_STATE.pop(event.sender_id, None)
                await event.reply(
                    f"✅ Account added.\nLabel: {label}\nSession file: {file_name}"
                )
            else:
                await event.reply("Please send a `.session` file.")
            return

        # حالت تنظیم پروکسی
        if state and state.get("mode") == "setting_proxy":
            account_id = state.get("account_id")

            # پاک کردن پروکسی
            if text.lower() == "none":
                await update_proxy(account_id, None, None, None, None)
                ADMIN_STATE.pop(event.sender_id, None)
                await event.reply(f"✅ Proxy cleared for account {account_id}.")
                return

            # host:port یا host:port:username:password
            parts = text.split(":")
            if len(parts) not in (2, 4):
                await event.reply(
                    "Invalid format.\nUse `host:port` or `host:port:username:password`."
                )
                return

            host = parts[0]
            try:
                port = int(parts[1])
            except ValueError:
                await event.reply("Port must be an integer.")
                return

            username = parts[2] if len(parts) == 4 else None
            password = parts[3] if len(parts) == 4 else None

            await update_proxy(account_id, host, port, username, password)
            ADMIN_STATE.pop(event.sender_id, None)
            await event.reply(f"✅ Proxy updated for account {account_id}.")
            return

        # اگر هیچ استیتی نبود، فعلاً پیام‌های معمولی رو نادیده می‌گیریم
        # (می‌تونی اینجا help یا چیزی اضافه کنی اگر خواستی)
        return

    @bot.on(events.CallbackQuery(pattern=re.compile(br"accounts:toggle:(\d+):(\d+)")))
    async def cb_accounts_toggle(event):
        if event.sender_id != ADMIN_ID:
            await event.answer("Access denied.", alert=True)
            return

        m = re.match(br"accounts:toggle:(\d+):(\d+)", event.data)
        if not m:
            await event.answer("Invalid data.", alert=True)
            return

        acc_id = int(m.group(1))
        page = int(m.group(2))

        updated = await toggle_account_active(acc_id)
        if not updated:
            await event.answer("Account not found.", alert=True)
            return

        status = "Active" if updated["is_active"] else "Inactive"
        await event.answer(f"Account {acc_id} is now {status}.", alert=True)

        # بعد از Toggle همون صفحه‌ای که بودیم رو دوباره نشون بده
        await show_accounts_page(event, page=page)


    @bot.on(events.CallbackQuery(pattern=re.compile(br"accounts:proxy:(\d+):(\d+)")))
    async def cb_accounts_proxy(event):
        if event.sender_id != ADMIN_ID:
            await event.answer("Access denied.", alert=True)
            return

        m = re.match(br"accounts:proxy:(\d+):(\d+)", event.data)
        if not m:
            await event.answer("Invalid data.", alert=True)
            return

        acc_id = int(m.group(1))
        # page = int(m.group(2))  # اگر بعداً خواستی بعد از ست‌کردن پروکسی صفحه رو رفرش کنی، این به درد می‌خوره

        ADMIN_STATE[event.sender_id] = {"mode": "setting_proxy", "account_id": acc_id}
        text = (
            f"🌐 Proxy settings for account {acc_id}\n\n"
            "Send proxy in one of these formats:\n"
            "`host:port`\n"
            "`host:port:username:password`\n\n"
            "To clear proxy, send `none`."
        )
        await event.reply(text)

    @bot.on(events.CallbackQuery(pattern=b"scheduler:start"))
    async def cb_scheduler_start(event):
        if event.sender_id != ADMIN_ID:
            await event.answer("Access denied.", alert=True)
            return
        start_scheduler()
        await event.answer("Scheduler started.", alert=True)
        await cb_menu_scheduler(event)

    @bot.on(events.CallbackQuery(pattern=b"scheduler:stop"))
    async def cb_scheduler_stop(event):
        if event.sender_id != ADMIN_ID:
            await event.answer("Access denied.", alert=True)
            return
        stop_scheduler()
        await event.answer("Scheduler stopped.", alert=True)
        await cb_menu_scheduler(event)
