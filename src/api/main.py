from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from typing import Dict, Any, Optional
from pydantic import BaseModel
from pathlib import Path
from telethon.tl.types import Channel, Chat, User

from src.core.state import GlobalState
from src.db.mongo.message_model import MongoMessageMedia


class AuthStartRequest(BaseModel):
    api_id: int
    api_hash: str
    phone_number: str
    session_name: Optional[str] = None


class AuthVerifyRequest(BaseModel):
    phone_number: str
    otp: str
    password: Optional[str] = None


def create_app(scrapper, db, auth_manager):
    app = FastAPI(title="Telethon Scraper Management API")
    app.state.scrapper = scrapper
    app.state.db = db
    app.state.auth_manager = auth_manager

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    web_dist = Path(__file__).resolve().parents[2] / "web" / "dist"
    index_file = web_dist / "index.html"
    assets_dir = web_dist / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="ui-assets")

    @app.get("/stats")
    async def get_stats():
        """Get overall scraper statistics."""
        return GlobalState.stats

    @app.get("/active-jobs")
    async def get_active_jobs():
        """Get real-time progress of current downloads."""
        return list(GlobalState.active_jobs.values())

    @app.get("/history")
    async def get_history(limit: int = 50, skip: int = 0):
        """Get history of scraped media from MongoDB."""
        history = await MongoMessageMedia.find().sort("-scraped_at").skip(skip).limit(limit).to_list()
        return history

    @app.get("/config")
    async def get_config():
        """Get current scraper configuration from DB."""
        if not app.state.scrapper:
            raise HTTPException(status_code=503, detail="Scraper not initialized")
        return app.state.scrapper._scraper_config

    @app.patch("/config")
    async def update_config(updates: Dict[str, Any]):
        """Update scraper configuration in DB."""
        if not app.state.scrapper:
            raise HTTPException(status_code=503, detail="Scraper not initialized")

        for key, value in updates.items():
            if hasattr(app.state.scrapper._scraper_config, key):
                setattr(app.state.scrapper._scraper_config, key, value)

        await app.state.scrapper._scraper_config.save()
        return app.state.scrapper._scraper_config

    @app.post("/chats")
    async def add_chat(chat_identifier: str):
        """Dynamically add a new chat to the scraper and persist it."""
        if not app.state.scrapper:
            raise HTTPException(status_code=503, detail="Scraper not initialized")

        success = await app.state.scrapper.add_chat(chat_identifier)
        if success:
            return {"status": "success", "message": f"Chat {chat_identifier} added and persisted"}
        else:
            raise HTTPException(status_code=400, detail=f"Failed to add chat {chat_identifier}")

    @app.get("/current-chats")
    async def get_chats():
        """List currently active chats in the scraper."""
        if not app.state.scrapper:
            return []
        return [getattr(c, "username", str(c.id)) for c in app.state.scrapper._valid_chats]

    @app.get("/enabled-chats")
    async def get_enabled_chats():
        """List chats enabled in config (persisted)."""
        status = await app.state.auth_manager.get_auth_status()
        owner_phone = status.get("phone_number") if status.get("authorized") else None

        if app.state.scrapper and owner_phone:
            return app.state.scrapper._scraper_config.chats

        if owner_phone:
            settings = await app.state.db.get_settings(owner_phone)
            return settings.chats

        return []

    @app.get("/available-chats")
    async def get_available_chats(limit: int = 200, include_users: bool = False):
        """List available dialogs for the authorized account."""
        try:
            client = await app.state.auth_manager.get_authorized_client()
        except Exception as e:
            raise HTTPException(status_code=503, detail=str(e))

        results = []
        async for dialog in client.iter_dialogs(limit=limit):
            entity = dialog.entity

            if isinstance(entity, User) and not include_users:
                continue

            if isinstance(entity, Channel):
                chat_type = "channel" if entity.broadcast else "group"
            elif isinstance(entity, Chat):
                chat_type = "group"
            elif isinstance(entity, User):
                chat_type = "user"
            else:
                chat_type = "unknown"

            results.append(
                {
                    "id": entity.id,
                    "title": getattr(entity, "title", None),
                    "username": getattr(entity, "username", None),
                    "type": chat_type,
                }
            )

        return results

    @app.post("/auth/start")
    async def auth_start(payload: AuthStartRequest):
        """Send OTP for Telegram login using provided credentials."""
        try:
            session_name = await app.state.auth_manager.start_auth(
                api_id=payload.api_id,
                api_hash=payload.api_hash,
                phone_number=payload.phone_number,
                session_name=payload.session_name,
            )
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

        return {
            "status": "otp_sent",
            "phone_number": payload.phone_number,
            "session_name": session_name,
        }

    @app.post("/auth/verify")
    async def auth_verify(payload: AuthVerifyRequest):
        """Verify OTP and finalize Telegram login."""
        try:
            await app.state.auth_manager.verify_auth(
                phone_number=payload.phone_number,
                otp=payload.otp,
                password=payload.password,
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

        return {"status": "authorized"}

    @app.get("/auth/status")
    async def auth_status():
        """Check whether a session is already authorized."""
        status = await app.state.auth_manager.get_auth_status()
        return status

    @app.post("/auth/logout")
    async def auth_logout():
        """Logout the current session."""
        await app.state.auth_manager.logout()
        return {"status": "logged_out"}

    if index_file.exists():
        @app.get("/")
        async def serve_ui():
            return FileResponse(str(index_file))

    return app
