import asyncio
import os
import sys

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
import hashlib
from datetime import datetime

class TelethonScrapper:
    def __init__(self, config: ConfigSchema, scrapper_config: ScraperSettings , db):
        self._config = config
        self._scraper_config = scrapper_config
        self._client: TelegramClient | None = None
        self._db = db

    """
    function to initialize and authenticate to the telegram with mt-proto session
    """

    async def initialize(self):
        try:
            self._client = TelegramClient(
                session=self._config.session_name,
                api_id=self._config.api_id,
                api_hash=self._config.api_hash,
            )

            await self._client.connect()

            if not await self._client.is_user_authorized():
                logger.info("User is not authorized")

                await self._client.send_code_request(self._config.phone_number)
                logger.info(f"please enter otp sent to: {self._config.phone_number}")

                otp = (await asyncio.to_thread(input, "Enter OTP: ")).strip()

                try:
                    await self._client.sign_in(
                        phone=self._config.phone_number, code=otp
                    )
                    logger.info("Sign in Successful")
                except Exception:
                    logger.exception("Login failed")
                    sys.exit(1)

        except Exception:
            logger.exception("Exception in initializing the Telethon")
            sys.exit(1)

    async def real_time_scrapping(self):
        valid_chats = []

        for chat in self._scraper_config.chats:
            try:
                entity = await self._client.get_entity(chat)
                valid_chats.append(entity)

            except Exception:
                logger.error(f"Invalid chat skipped: {chat}")

        if not valid_chats:
            logger.warning(
                "No valid chats found. Scraper will not listen to any chats."
            )
            return

        self._client.add_event_handler(
            self.handle_event, events.NewMessage(chats=valid_chats)
        )

        logger.info(f"Realtime scraping started for {len(valid_chats)} chats")
        await self._client.run_until_disconnected()

    async def historical_scrapping(self):
        if not self._scraper_config.history_enabled:
            logger.info("Historical scraping is disabled in config.")
            return

        valid_chats = []

        for chat in self._scraper_config.chats:
            try:
                entity = await self._client.get_entity(chat)
                valid_chats.append(entity)
            except Exception:
                logger.error(f"Invalid chat skipped: {chat}")

        if not valid_chats:
            logger.warning("No valid chats found for historical scraping.")
            return

        logger.info(f"Starting historical scraping for {len(valid_chats)} chats")

        for chat in valid_chats:
            logger.info(f"Fetching history for chat: {chat.id}")

            async for message in self._client.iter_messages(
                chat,
                limit=self._scraper_config.history_limit
            ):
                if not message:
                    continue

                # Wrap message in pseudo event style logic
                if message.media:
                    await self._handle_media(message)

        logger.info("Historical scraping completed.")
        
    async def handle_event(self, event):
        message = event.message
        logger.info(f"New message received | chat_id={event.chat_id}")

        chat = await event.get_chat()
        if not self._is_allowed_chat_type(chat):
            logger.warning("Chat type is not supported supported streams channel / user / group")
            return

        # MEDIA SCRAPING
        if message.media:
            await self._handle_media(message)

    def _is_allowed_chat_type(self, chat) -> bool:
        if isinstance(chat, Channel):
            if chat.broadcast and ChatType.CHANNEL in self._scraper_config.chat_types:
                return True

            if chat.megagroup and ChatType.GROUP in self._scraper_config.chat_types:
                return True

        if isinstance(chat, Chat):
            if ChatType.GROUP in self._scraper_config.chat_types:
                return True

        if isinstance(chat, User):
            if ChatType.USER in self._scraper_config.chat_types:
                return True

        return False

    async def _handle_media(self, message):
        if not self._scraper_config.media_enabled:
            return

        file = message.file
        if not file:
            return

        # ---- Size filtering ----
        if file.size:
            size_kb = file.size / 1024
            size_mb = size_kb / 1024

            if self._scraper_config.min_file_size_kb and size_kb < self._scraper_config.min_file_size_kb:
                return

            if self._scraper_config.max_file_size_mb and size_mb > self._scraper_config.max_file_size_mb:
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

        # ---- Create hash for deduplication ----
        hash_input = f"{file_name}-{file_size}-{access_hash}"
        file_hash = hashlib.sha256(hash_input.encode()).hexdigest()

        # ---- Insert PENDING record ----
        mongo_data = {
            "chat_type": str(type(await message.get_chat()).__name__),
            "chat_name": (await message.get_chat()).username or "unknown",
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
            """
            file already exists in the database no need to add duplicates
            """
            return

        try:
            # ---- Update status to DOWNLOADING ----
            await self._db.update_status(str(db_doc.id), DownloadStatus.DOWNLOADING)

            if self._scraper_config.download_media:
                os.makedirs(self._scraper_config.download_path, exist_ok=True)
                
                logger.info("Downloading started...")

                file_path = await message.download_media(
                    file=self._scraper_config.download_path
                )

                logger.info(f"Media downloaded: {file_path}")

            # ---- Update status to DONE ----
            await self._db.update_status(str(db_doc.id), DownloadStatus.DONE)

        except Exception as e:
            logger.exception("Download failed")

            # ---- Update status to FAILED ----
            await self._db.update_status(str(db_doc.id), DownloadStatus.FAILED)
            
            
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
        await self.initialize()
        await self.historical_scrapping()
        await self.real_time_scrapping()
