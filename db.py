# db.py

import aiosqlite
from typing import Optional, List, Dict, Any
from datetime import datetime
from config import DB_PATH


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
        CREATE TABLE IF NOT EXISTS accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            label TEXT,
            session_path TEXT,
            is_active INTEGER DEFAULT 1,
            created_groups_count INTEGER DEFAULT 0,
            first_activity_at TEXT,
            last_group_created_at TEXT,
            proxy_host TEXT,
            proxy_port INTEGER,
            proxy_username TEXT,
            proxy_password TEXT
        );
        """)
        await db.execute("""
        CREATE TABLE IF NOT EXISTS groups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER,
            chat_id TEXT,
            title TEXT,
            created_at TEXT,
            messages_sent INTEGER DEFAULT 0,
            FOREIGN KEY(account_id) REFERENCES accounts(id)
        );
        """)
        await db.execute("""
        CREATE TABLE IF NOT EXISTS errors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER,
            context TEXT,
            error_text TEXT,
            created_at TEXT,
            FOREIGN KEY(account_id) REFERENCES accounts(id)
        );
        """)
        await db.commit()


async def add_account(label: str, session_path: str) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "INSERT INTO accounts (label, session_path, is_active) VALUES (?, ?, 1)",
            (label, session_path),
        )
        await db.commit()
        return cursor.lastrowid


async def get_accounts(active_only: bool = False) -> List[Dict[str, Any]]:
    query = "SELECT * FROM accounts"
    params = ()
    if active_only:
        query += " WHERE is_active = 1"
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(query, params)
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def get_account_by_id(account_id: int) -> Optional[Dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM accounts WHERE id = ?", (account_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None


async def delete_account(account_id: int) -> bool:
    """Delete an account and all related data (groups, errors).
    
    Args:
        account_id: The ID of the account to delete
        
    Returns:
        True if account was deleted, False if not found
    """
    import os
    
    # Get account info first
    account = await get_account_by_id(account_id)
    if not account:
        return False
    
    async with aiosqlite.connect(DB_PATH) as db:
        # Delete related groups
        await db.execute("DELETE FROM groups WHERE account_id = ?", (account_id,))
        
        # Delete related errors
        await db.execute("DELETE FROM errors WHERE account_id = ?", (account_id,))
        
        # Delete the account itself
        await db.execute("DELETE FROM accounts WHERE id = ?", (account_id,))
        
        await db.commit()
    
    # Try to delete session file
    try:
        from config import SESSIONS_DIR
        session_path = account.get("session_path", "")
        if session_path:
            full_path = os.path.join(SESSIONS_DIR, session_path)
            if not full_path.endswith(".session"):
                full_path += ".session"
            if os.path.exists(full_path):
                os.remove(full_path)
    except Exception:
        pass  # Ignore session file deletion errors
    
    return True


async def toggle_account_active(account_id: int) -> Optional[Dict[str, Any]]:
    account = await get_account_by_id(account_id)
    if not account:
        return None
    new_state = 0 if account["is_active"] else 1
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE accounts SET is_active = ? WHERE id = ?",
            (new_state, account_id),
        )
        await db.commit()
    account["is_active"] = new_state
    return account


async def update_proxy(
    account_id: int,
    host: Optional[str],
    port: Optional[int],
    username: Optional[str],
    password: Optional[str],
):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            UPDATE accounts
            SET proxy_host = ?, proxy_port = ?, proxy_username = ?, proxy_password = ?
            WHERE id = ?
            """,
            (host, port, username, password, account_id),
        )
        await db.commit()


async def create_group_record(
    account_id: int, chat_id: str, title: str, created_at: datetime
) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """
            INSERT INTO groups (account_id, chat_id, title, created_at, messages_sent)
            VALUES (?, ?, ?, ?, 0)
            """,
            (account_id, str(chat_id), title, created_at.isoformat()),
        )
        await db.commit()
        return cursor.lastrowid


async def update_group_messages_sent(group_id: int, count: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE groups SET messages_sent = ? WHERE id = ?",
            (count, group_id),
        )
        await db.commit()


async def increment_account_groups(account_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            UPDATE accounts
            SET created_groups_count = created_groups_count + 1
            WHERE id = ?
            """,
            (account_id,),
        )
        await db.commit()


async def update_account_activity(
    account_id: int,
    first_activity_at: Optional[datetime],
    last_group_created_at: datetime,
):
    async with aiosqlite.connect(DB_PATH) as db:
        if first_activity_at:
            await db.execute(
                """
                UPDATE accounts
                SET first_activity_at = ?, last_group_created_at = ?
                WHERE id = ?
                """,
                (
                    first_activity_at.isoformat(),
                    last_group_created_at.isoformat(),
                    account_id,
                ),
            )
        else:
            await db.execute(
                """
                UPDATE accounts
                SET last_group_created_at = ?
                WHERE id = ?
                """,
                (
                    last_group_created_at.isoformat(),
                    account_id,
                ),
            )
        await db.commit()


async def log_error(
    context: str,
    error_text: str,
    account_id: Optional[int] = None,
):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO errors (account_id, context, error_text, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (account_id, context, error_text[:2000], datetime.utcnow().isoformat()),
        )
        await db.commit()


async def get_latest_errors(limit: int = 10) -> List[Dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM errors ORDER BY id DESC LIMIT ?", (limit,)
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def get_global_stats() -> Dict[str, Any]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        cursor = await db.execute("SELECT COUNT(*) as cnt FROM accounts")
        total_accounts = (await cursor.fetchone())["cnt"]

        cursor = await db.execute(
            "SELECT COUNT(*) as cnt FROM accounts WHERE is_active = 1"
        )
        active_accounts = (await cursor.fetchone())["cnt"]

        cursor = await db.execute(
            "SELECT SUM(created_groups_count) as total_groups FROM accounts"
        )
        row = await cursor.fetchone()
        total_groups = row["total_groups"] if row["total_groups"] is not None else 0

        cursor = await db.execute(
            "SELECT id, label, created_groups_count, is_active, proxy_host FROM accounts ORDER BY id"
        )
        accounts = [dict(r) for r in await cursor.fetchall()]

    return {
        "total_accounts": total_accounts,
        "active_accounts": active_accounts,
        "total_groups": total_groups,
        "accounts": accounts,
    }
