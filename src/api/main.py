from fastapi import FastAPI, HTTPException
from typing import List, Dict, Any
from src.core.state import GlobalState
from src.db.mongo.message_model import MongoMessageMedia
from src.db.mongo.settings_model import MongoScraperSettings

def create_app(scrapper, db):
    app = FastAPI(title="Telethon Scraper Management API")

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
        return scrapper._scraper_config

    @app.patch("/config")
    async def update_config(updates: Dict[str, Any]):
        """Update scraper configuration in DB."""
        for key, value in updates.items():
            if hasattr(scrapper._scraper_config, key):
                setattr(scrapper._scraper_config, key, value)
        
        await scrapper._scraper_config.save()
        return scrapper._scraper_config

    @app.post("/chats")
    async def add_chat(chat_identifier: str):
        """Dynamically add a new chat to the scraper and persist it."""
        success = await scrapper.add_chat(chat_identifier)
        if success:
            return {"status": "success", "message": f"Chat {chat_identifier} added and persisted"}
        else:
            raise HTTPException(status_code=400, detail=f"Failed to add chat {chat_identifier}")

    @app.get("/current-chats")
    async def get_chats():
        """List currently active chats in the scraper."""
        return [getattr(c, "username", str(c.id)) for c in scrapper._valid_chats]

    return app
