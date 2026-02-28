from beanie import Document
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from enum import Enum


class DownloadStatus(str, Enum):
    PENDING = "pending"
    DOWNLOADING = "downloading"
    DONE = "done"
    FAILED = "failed"


class MongoExtraReference(BaseModel):
    channel_name: str
    message_id : int
    message_date : datetime


class MongoMessageMedia(Document):
    chat_type: str
    chat_name: str

    message_id: int
    message_date: datetime
    scraped_at: datetime

    status: DownloadStatus = DownloadStatus.PENDING

    filename: str
    file_type: str
    mime_type: str
    file_size: int
    file_hash: str

    extra_refs: Optional[MongoExtraReference] = None

    access_hash: int

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "media_messages"
        indexes = [
        {"key": [("file_hash", 1)], "unique": True},
        {"key": [("status", 1)]},
        ]