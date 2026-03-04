import uvloop
import asyncio
import sys
import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from loguru import logger
from telethon import TelegramClient

from src.core.config import Config
from src.core.srrapper_config import ScraperConfig
from src.db.mongo.mongo_db import MongoDB
from src.services.telethon import TelethonScrapper
from src.services.download import DownloadService
from src.api.main import create_app


class OTPPayload(BaseModel):
    otp: str


async def wait_for_otp_via_api(port: int = 8080) -> str:
    """
    Spin up a temporary FastAPI server on the given port.
    Waits until the UI POSTs the OTP to /auth/otp, then shuts down
    the server and returns the OTP string.
    """
    otp_future: asyncio.Future = asyncio.get_event_loop().create_future()

    auth_app = FastAPI(title="Telegram Auth")

    @auth_app.get("/auth/status")
    async def auth_status():
        """UI can poll this to know whether to show the OTP form."""
        return {"authorized": False, "waiting_for_otp": True}

    @auth_app.post("/auth/otp")
    async def submit_otp(payload: OTPPayload):
        """UI submits the OTP here."""
        otp = payload.otp.strip()
        if not otp:
            raise HTTPException(status_code=400, detail="otp field must not be empty")
        if otp_future.done():
            raise HTTPException(status_code=409, detail="OTP already submitted")
        otp_future.set_result(otp)
        return {"status": "success", "message": "OTP received, signing in..."}

    cfg = uvicorn.Config(app=auth_app, host="0.0.0.0", port=port, log_level="info")
    server = uvicorn.Server(cfg)

    server_task = asyncio.create_task(server.serve())
    logger.info(
        f"Waiting for OTP via API — POST http://0.0.0.0:{port}/auth/otp  body: {{\"otp\": \"<code>\"}}"
    )

    # Block until the UI submits the OTP
    otp = await otp_future

    # Gracefully shut down the auth server before continuing
    server.should_exit = True
    await server_task

    return otp


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

        # OTP is now received via API instead of command-line input
        otp = await wait_for_otp_via_api(port=8080)

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
