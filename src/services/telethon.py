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

from src.core.srrapper_config import ChatType, MediaType
from src.schema.telethon_schema import ConfigSchema
from src.db.mongo.message_model import DownloadStatus
from src.db.mongo.settings_model import MongoScraperSettings
from src.services.download import DownloadService


class TelethonScrapper:
    def __init__(
        self, 
        client: TelegramClient,
        config: ConfigSchema, 
        scrapper_config: MongoScraperSettings, 
        db,
        download_service: DownloadService
    ):
        self._client = client
        self._config = config
        self._scraper_config = scrapper_config
        self._db = db
        self._download_service = download_service
        self._valid_chats = []

    async def add_chat(self, chat_identifier: str):
        """Dynamically add a new chat to the scraper and persist to DB."""
        try:
            entity = await self._client.get_entity(chat_identifier)
            
            # Persist to DB if not already there
            if chat_identifier not in self._scraper_config.chats:
                self._scraper_config.chats.append(chat_identifier)
                await self._scraper_config.save()
                logger.info(f"Persisted new chat to DB: {chat_identifier}")

            if entity not in self._valid_chats:
                self._valid_chats.append(entity)
                
                # Update event handler to include the new chat
                self._client.remove_event_handler(self.handle_event)
                self._client.add_event_handler(
                    self.handle_event, events.NewMessage(chats=self._valid_chats)
                )
                
                logger.info(f"Dynamically activated chat: {chat_identifier}")
                
                # Start historical scraping for this new chat in background
                asyncio.create_task(self.scrape_history_for_chat(entity))
                return True
        except Exception as e:
            logger.error(f"Failed to add chat {chat_identifier}: {e}")
            return False

    async def scrape_history_for_chat(self, entity):
        """Scrape history for a specific entity."""
        if not self._scraper_config.history_enabled:
            return

        logger.info(f"Fetching history for new chat: {entity.id}")
        async for message in self._client.iter_messages(
            entity,
            limit=self._scraper_config.history_limit
        ):
            if message and message.media:
                await self._handle_media(message)

    async def real_time_scrapping(self):
        self._valid_chats = []

        for chat in self._scraper_config.chats:
            try:
                entity = await self._client.get_entity(chat)
                self._valid_chats.append(entity)
            except Exception:
                logger.error(f"Invalid chat skipped: {chat}")

        if not self._valid_chats:
            logger.warning("No valid chats found.")
            # Even if no chats, we should keep the client running to allow dynamic additions
            # but we need at least one handler or use run_until_disconnected
        else:
            self._client.add_event_handler(
                self.handle_event, events.NewMessage(chats=self._valid_chats)
            )
            logger.info(f"Realtime scraping started for {len(self._valid_chats)} chats")

        await self._client.run_until_disconnected()

    async def historical_scrapping(self):
        if not self._scraper_config.history_enabled:
            logger.info("Historical scraping disabled.")
            return

        if not self._valid_chats:
            return

        logger.info(f"Starting historical scraping for {len(self._valid_chats)} chats")

        for chat in self._valid_chats:
            await self.scrape_history_for_chat(chat)

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
            "chat_name": getattr(chat, "username", None) or getattr(chat, "title", "unknown"),
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
        # Initial setup of valid chats
        await self.real_time_scrapping()
        # Historical scrapping is now triggered by real_time_scrapping initialization
        # but we also want it for the initial batch:
        asyncio.create_task(self.historical_scrapping())
