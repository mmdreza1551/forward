# accounts.py

import os
from typing import Dict, Optional, Tuple
from datetime import datetime

import socks  # PySocks
from telethon import TelegramClient
from config import API_ID, API_HASH, SESSIONS_DIR
from db import get_accounts

# account_id -> TelegramClient
ACCOUNT_CLIENTS: Dict[int, TelegramClient] = {}


def ensure_sessions_dir():
    if not os.path.exists(SESSIONS_DIR):
        os.makedirs(SESSIONS_DIR, exist_ok=True)


def build_proxy_tuple(
    host: Optional[str],
    port: Optional[int],
    username: Optional[str],
    password: Optional[str],
) -> Optional[Tuple]:
    if not host or not port:
        return None
    if username and password:
        return (socks.SOCKS5, host, int(port), True, username, password)
    else:
        return (socks.SOCKS5, host, int(port))


async def get_or_create_client(account_row: dict) -> TelegramClient:
    """
    Returns a connected TelegramClient for this account.
    Reuses existing one if present.
    """
    account_id = account_row["id"]
    if account_id in ACCOUNT_CLIENTS:
        client = ACCOUNT_CLIENTS[account_id]
        if not client.is_connected():
            await client.connect()
        return client

    ensure_sessions_dir()
    session_path = account_row["session_path"]
    if not os.path.isabs(session_path):
        session_path = os.path.join(SESSIONS_DIR, session_path)

    proxy = build_proxy_tuple(
        account_row.get("proxy_host"),
        account_row.get("proxy_port"),
        account_row.get("proxy_username"),
        account_row.get("proxy_password"),
    )

    client = TelegramClient(
        session=session_path,
        api_id=API_ID,
        api_hash=API_HASH,
        proxy=proxy,
        device_model="POCO POCO X6 Pro 5G",
        system_version="Android 15",
        app_version="11.13.0.1",
        lang_code="en",
        system_lang_code="en",
    )


    await client.connect()
    ACCOUNT_CLIENTS[account_id] = client
    return client


async def disconnect_all_clients():
    for client in ACCOUNT_CLIENTS.values():
        try:
            await client.disconnect()
        except Exception:
            pass
    ACCOUNT_CLIENTS.clear()
