from fastapi import FastAPI, HTTPException
from typing import List, Dict, Any
from src.core.state import GlobalState
from src.db.mongo.message_model import MongoMessageMedia

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

    @app.post("/chats")
    async def add_chat(chat_identifier: str):
        """Dynamically add a new chat to the scraper."""
        success = await scrapper.add_chat(chat_identifier)
        if success:
            return {"status": "success", "message": f"Chat {chat_identifier} added"}
        else:
            raise HTTPException(status_code=400, detail=f"Failed to add chat {chat_identifier}")

    @app.get("/current-chats")
    async def get_chats():
        """List currently active chats in the scraper."""
        return [getattr(c, "username", str(c.id)) for c in scrapper._valid_chats]

    return app
