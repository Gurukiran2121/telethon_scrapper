import uvloop
import asyncio
import sys
import uvicorn
from loguru import logger
from telethon import TelegramClient

from src.core.config import Config
from src.core.srrapper_config import ScraperConfig
from src.db.mongo.mongo_db import MongoDB
from src.services.telethon import TelethonScrapper
from src.services.download import DownloadService
from src.api.main import create_app


async def main():
    # 1. Initialize MongoDB
    mongo = MongoDB(db_name=Config.db_name, uri=Config.db_uri)
    await mongo.init()
    logger.info("MongoDB initialized...")

    # 1a. Fetch Dynamic Scraper Settings
    scraper_settings = await mongo.get_settings()
    logger.info(f"Scraper settings loaded from DB: {scraper_settings.chats}")

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
    download_service = DownloadService(
        client=client, 
        db=mongo, 
        max_concurrent_files=Config.max_concurrent_files
    )
    await download_service.start()
    logger.info(f"Download Service initialized...")

    # 4. Initialize Telethon Scrapper
    telethon = TelethonScrapper(
        client=client,
        config=Config, 
        scrapper_config=scraper_settings, 
        db=mongo,
        download_service=download_service
    )

    # 5. Setup FastAPI
    app = create_app(telethon, mongo)
    
    # Configure Uvicorn to run alongside our scraper
    config = uvicorn.Config(app=app, host="0.0.0.0", port=8080, log_level="info")
    server = uvicorn.Server(config)

    logger.info("Starting Telethon scrapper and API server...")
    
    # Run both as concurrent tasks
    await asyncio.gather(
        telethon.run(),
        server.serve()
    )


if __name__ == "__main__":
    uvloop.run(main())
