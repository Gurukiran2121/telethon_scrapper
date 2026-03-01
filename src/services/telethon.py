import asyncio
import os
import sys
import time
import hashlib
from datetime import datetime

from loguru import logger
from telethon import TelegramClient, events
from telethon.tl.types import (
    Channel,
    Chat,
    MessageMediaDocument,
    MessageMediaPhoto,
    User,
)

from src.core.srrapper_config import ChatType, MediaType, ScraperSettings
from src.schema.telethon_schema import ConfigSchema
from src.db.mongo.message_model import DownloadStatus
from src.services.download import DownloadService


class TelethonScrapper:
    def __init__(
        self, 
        client: TelegramClient,
        config: ConfigSchema, 
        scrapper_config: ScraperSettings, 
        db,
        download_service: DownloadService
    ):
        self._client = client
        self._config = config
        self._scraper_config = scrapper_config
        self._db = db
        self._download_service = download_service

    async def real_time_scrapping(self):
        valid_chats = []

        for chat in self._scraper_config.chats:
            try:
                entity = await self._client.get_entity(chat)
                valid_chats.append(entity)
            except Exception:
                logger.error(f"Invalid chat skipped: {chat}")

        if not valid_chats:
            logger.warning("No valid chats found.")
            return

        self._client.add_event_handler(
            self.handle_event, events.NewMessage(chats=valid_chats)
        )

        logger.info(f"Realtime scraping started for {len(valid_chats)} chats")
        # Note: run_until_disconnected should be called in main or handled appropriately
        await self._client.run_until_disconnected()

    async def historical_scrapping(self):
        if not self._scraper_config.history_enabled:
            logger.info("Historical scraping disabled.")
            return

        valid_chats = []

        for chat in self._scraper_config.chats:
            try:
                entity = await self._client.get_entity(chat)
                valid_chats.append(entity)
            except Exception:
                logger.error(f"Invalid chat skipped: {chat}")

        if not valid_chats:
            logger.warning("No valid chats found for history.")
            return

        logger.info(f"Starting historical scraping for {len(valid_chats)} chats")

        for chat in valid_chats:
            logger.info(f"Fetching history for chat: {chat.id}")

            async for message in self._client.iter_messages(
                chat,
                limit=self._scraper_config.history_limit
            ):
                if message and message.media:
                    await self._handle_media(message)

        logger.info("Historical scraping completed.")

    async def handle_event(self, event):
        message = event.message
        logger.info(f"New message received | chat_id={event.chat_id}")

        chat = await event.get_chat()
        if not self._is_allowed_chat_type(chat):
            return

        if message.media:
            await self._handle_media(message)

    def _is_allowed_chat_type(self, chat) -> bool:
        if isinstance(chat, Channel):
            if chat.broadcast and ChatType.CHANNEL in self._scraper_config.chat_types:
                return True
            if chat.megagroup and ChatType.GROUP in self._scraper_config.chat_types:
                return True

        if isinstance(chat, Chat):
            return ChatType.GROUP in self._scraper_config.chat_types

        if isinstance(chat, User):
            return ChatType.USER in self._scraper_config.chat_types

        return False

    async def _handle_media(self, message):
        if not self._scraper_config.media_enabled:
            return

        file = message.file
        if not file:
            return

        media_type = self._detect_media_type(message)
        if not media_type:
            return

        if not self._scraper_config.media_types.get(media_type, False):
            return

        file_name = file.name or ""
        mime_type = file.mime_type or ""
        file_size = file.size or 0

        access_hash = None
        if isinstance(message.media, MessageMediaDocument):
            access_hash = message.media.document.access_hash

        # Generate file hash
        hash_input = f"{file_name}-{file_size}-{access_hash}"
        file_hash = hashlib.sha256(hash_input.encode()).hexdigest()

        chat = await message.get_chat()

        mongo_data = {
            "chat_type": type(chat).__name__,
            "chat_name": getattr(chat, "username", None) or "unknown",
            "message_id": message.id,
            "message_date": message.date,
            "scraped_at": datetime.utcnow(),
            "status": DownloadStatus.PENDING,
            "filename": file_name,
            "file_type": file_name.split(".")[-1] if "." in file_name else "",
            "mime_type": mime_type,
            "file_size": file_size,
            "file_hash": file_hash,
            "access_hash": access_hash,
        }

        db_doc = await self._db.create(mongo_data)
        if not db_doc:
            return  # Duplicate

        if self._scraper_config.download_media:
            # Enqueue for asynchronous download
            await self._download_service.enqueue_download(message, str(db_doc.id))

    def _detect_media_type(self, message) -> MediaType | None:
        if isinstance(message.media, MessageMediaPhoto):
            return MediaType.PHOTO

        if isinstance(message.media, MessageMediaDocument):
            mime = message.file.mime_type or ""
            if "video" in mime:
                return MediaType.VIDEO
            if "audio" in mime:
                return MediaType.AUDIO
            if "gif" in mime:
                return MediaType.GIF
            return MediaType.DOCUMENT

        return None

    async def run(self):
        # We start historical scraping in a task so it doesn't block real-time scraping setup
        asyncio.create_task(self.historical_scrapping())
        await self.real_time_scrapping()
