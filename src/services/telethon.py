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


class TelethonScrapper:
    def __init__(self, config: ConfigSchema, scrapper_config: ScraperSettings):
        self._config = config
        self._scraper_config = scrapper_config
        self._client: TelegramClient | None = None

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
        """
        if no media is enabled than return
        """
        if not self._scraper_config.media_enabled:
            logger.warning("Media scrapping is not enabled in configuration please enable it scrap the media")
            return

        """
        if no file found just return
        """
        file = message.file
        if not file:
            logger.warning("No attached file found in the message.")
            return

        """
        check for the file size range filter
        """
        if file.size:
            size_kb = file.size / 1024
            size_mb = size_kb / 1024

            if self._scraper_config.min_file_size_kb is not None:
                if size_kb < self._scraper_config.min_file_size_kb:
                    logger.warning("File size is not in the defined range check config to increase or decrease the limit")
                    return

            if self._scraper_config.max_file_size_mb is not None:
                if size_mb > self._scraper_config.max_file_size_mb:
                    logger.warning("File size is not in the defined range check config to increase or decrease the limit")
                    return

        """
        if no media type than return
        """
        media_type = self._detect_media_type(message)
        if not media_type:
            logger.warning("type of media is not supported")
            return

        if not self._scraper_config.media_types.get(media_type, False):
            return

        logger.info(f"Media detected: {media_type}")

        """
        check if the file type is supported by configuration if not return
        """
        file_name = file.name or ""
        if self._scraper_config.allowed_file_extensions:
            if not any(
                file_name.lower().endswith(ext.lower())
                for ext in self._scraper_config.allowed_file_extensions
            ):
                return

        # MIME check
        mime_type = file.mime_type or ""
        if self._scraper_config.allowed_mime_types:
            if not any(
                allowed in mime_type
                for allowed in self._scraper_config.allowed_mime_types
            ):
                return

        """
        if media download is enabled in teh cofig and path is avilable download the media
        """
        if self._scraper_config.download_media:
            os.makedirs(self._scraper_config.download_path, exist_ok=True)
            logger.info("media downloaded started")
            file_path = await message.download_media(
                file=self._scraper_config.download_path
            )

            logger.info(f"Media downloaded: {file_path}")

        else:
            logger.info("Media metadata captured (download disabled)")

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
