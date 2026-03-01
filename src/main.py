import uvloop
import asyncio
import sys
from loguru import logger
from telethon import TelegramClient

from src.core.config import Config
from src.core.srrapper_config import ScraperConfig
from src.db.mongo.mongo_db import MongoDB
from src.services.telethon import TelethonScrapper
from src.services.download import DownloadService


async def main():
    # 1. Initialize MongoDB
    mongo = MongoDB(db_name=Config.db_name, uri=Config.db_uri)
    await mongo.init()
    logger.info("MongoDB initialized...")

    # 2. Initialize Telethon Client
    client = TelegramClient(
        session=Config.session_name,
        api_id=Config.api_id,
        api_hash=Config.api_hash,
    )

    await client.connect()

    if not await client.is_user_authorized():
        logger.info("User is not authorized")
        await client.send_code_request(Config.phone_number)
        otp = (await asyncio.to_thread(input, "Enter OTP: ")).strip()
        try:
            await client.sign_in(phone=Config.phone_number, code=otp)
            logger.info("Sign in Successful")
        except Exception:
            logger.exception("Login failed")
            sys.exit(1)

    # 3. Initialize High-Performance Download Service
    # max_concurrent_files defines how many parallel file pipelines to run
    download_service = DownloadService(
        client=client, 
        db=mongo, 
        max_concurrent_files=Config.max_concurrent_files
    )
    await download_service.start()
    logger.info(f"Download Service initialized with {Config.max_concurrent_files} concurrent pipelines...")

    # 4. Initialize Telethon Scrapper
    telethon = TelethonScrapper(
        client=client,
        config=Config, 
        scrapper_config=ScraperConfig, 
        db=mongo,
        download_service=download_service
    )

    logger.info("Telethon scrapper starting...")
    await telethon.run()


if __name__ == "__main__":
    uvloop.run(main())
