import asyncio
import re
from typing import Optional

from loguru import logger
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError

from src.db.mongo.mongo_db import MongoDB
from src.core.config import Config


class AuthManager:
    def __init__(self, db: MongoDB):
        self._db = db
        self._pending: dict[str, TelegramClient] = {}
        self._authorized_client: Optional[TelegramClient] = None
        self._authorized_event = asyncio.Event()
        self._lock = asyncio.Lock()

    async def start_auth(
        self,
        api_id: int,
        api_hash: str,
        phone_number: str,
        session_name: Optional[str] = None,
    ) -> str:
        session_name = session_name or self._default_session_name(phone_number)

        async with self._lock:
            existing = self._pending.get(phone_number)
            if existing:
                await existing.disconnect()

            client = TelegramClient(session=session_name, api_id=api_id, api_hash=api_hash)
            await client.connect()
            await client.send_code_request(phone_number)
            self._pending[phone_number] = client

            await self._db.upsert_auth_config(
                {
                    "api_id": api_id,
                    "api_hash": api_hash,
                    "phone_number": phone_number,
                    "session_name": session_name,
                }
            )

        logger.info(f"OTP sent for {phone_number}")
        return session_name

    async def verify_auth(
        self,
        phone_number: str,
        otp: str,
        password: Optional[str] = None,
    ) -> bool:
        async with self._lock:
            client = self._pending.get(phone_number)
            if not client:
                raise ValueError("No pending auth for this phone number")

            try:
                await client.sign_in(phone=phone_number, code=otp)
            except SessionPasswordNeededError:
                if not password:
                    raise ValueError("Two-factor password required")
                await client.sign_in(password=password)

            self._authorized_client = client
            self._authorized_event.set()
            self._pending.pop(phone_number, None)

        logger.info(f"Auth verified for {phone_number}")
        return True

    async def get_authorized_client(self) -> TelegramClient:
        if self._authorized_client:
            return self._authorized_client

        auth_config = await self._db.get_auth_config()
        if auth_config:
            client = TelegramClient(
                session=auth_config.session_name,
                api_id=auth_config.api_id,
                api_hash=auth_config.api_hash,
            )
            await client.connect()
            if await client.is_user_authorized():
                self._authorized_client = client
                return client

        # Fallback to environment config if no auth config exists
        try:
            client = TelegramClient(
                session=Config.session_name,
                api_id=Config.api_id,
                api_hash=Config.api_hash,
            )
            await client.connect()
            if await client.is_user_authorized():
                self._authorized_client = client
                return client
            await client.disconnect()
        except Exception:
            pass

        await self._authorized_event.wait()
        return self._authorized_client

    def _default_session_name(self, phone_number: str) -> str:
        digits = re.sub(r"[^0-9]", "", phone_number)
        return f"telethon_{digits}" if digits else "telethon_session"