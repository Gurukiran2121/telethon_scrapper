from typing import Dict, Any, List
from pydantic import BaseModel, Field
from datetime import datetime

class ActiveJob(BaseModel):
    message_id: int
    filename: str
    chat_name: str
    total_size: int
    downloaded_size: int = 0
    progress_percent: float = 0.0
    speed_mb_s: float = 0.0
    status: str = "active"
    started_at: datetime = Field(default_factory=datetime.utcnow)

class AppState:
    def __init__(self):
        self.active_jobs: Dict[int, ActiveJob] = {}
        self.stats = {
            "total_files_scraped": 0,
            "total_size_mb": 0.0,
            "start_time": datetime.utcnow()
        }

    def update_job(self, message_id: int, **kwargs):
        if message_id in self.active_jobs:
            job = self.active_jobs[message_id]
            for key, value in kwargs.items():
                setattr(job, key, value)
        else:
            self.active_jobs[message_id] = ActiveJob(message_id=message_id, **kwargs)

    def remove_job(self, message_id: int):
        if message_id in self.active_jobs:
            del self.active_jobs[message_id]

    def add_to_stats(self, size_bytes: int):
        self.stats["total_files_scraped"] += 1
        self.stats["total_size_mb"] += size_bytes / (1024 * 1024)

# Global singleton
GlobalState = AppState()
