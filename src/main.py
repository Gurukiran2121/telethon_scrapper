import uvloop
import asyncio
import uvicorn
from loguru import logger

from src.core.config import Config
from src.db.mongo.mongo_db import MongoDB
from src.services.telethon import TelethonScrapper
from src.services.download import DownloadService
from src.services.auth import AuthManager
from src.api.main import create_app


async def main():
    # 1. Initialize MongoDB
    mongo = MongoDB(db_name=Config.db_name, uri=Config.db_uri)
    await mongo.init()
    logger.info("MongoDB initialized...")

    # 1a. Fetch Dynamic Scraper Settings
    scraper_settings = await mongo.get_settings()
    logger.info(f"Scraper settings loaded from DB: {scraper_settings.chats}")

    # 2. Initialize Auth Manager and API
    auth_manager = AuthManager(db=mongo)
    app = create_app(scrapper=None, db=mongo, auth_manager=auth_manager)

    config = uvicorn.Config(app=app, host="0.0.0.0", port=8080, log_level="info")
    server = uvicorn.Server(config)
    server_task = asyncio.create_task(server.serve())

    logger.info("API server started. Waiting for Telegram authorization...")

    # 3. Wait for authorized client (via /auth/start + /auth/verify)
    client = await auth_manager.get_authorized_client()
    logger.info("Telegram client authorized")

    # 4. Initialize High-Performance Download Service
    download_service = DownloadService(
        client=client,
        db=mongo,
        max_concurrent_files=Config.max_concurrent_files,
    )
    await download_service.start()
    logger.info("Download Service initialized...")

    # 5. Initialize Telethon Scrapper
    telethon = TelethonScrapper(
        client=client,
        config=Config,
        scrapper_config=scraper_settings,
        db=mongo,
        download_service=download_service,
    )

    app.state.scrapper = telethon

    logger.info("Starting Telethon scrapper and API server...")

    telethon_task = asyncio.create_task(telethon.run())
    await asyncio.gather(telethon_task, server_task)


if __name__ == "__main__":
    uvloop.run(main())
