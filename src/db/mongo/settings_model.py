from typing import Dict, List, Optional
from beanie import Document
from pydantic import Field
from src.core.srrapper_config import MediaType, ChatType

class MongoScraperSettings(Document):
    media_enabled: bool = True
    media_types: Dict[MediaType, bool] = Field(
        default_factory=lambda: {
            MediaType.PHOTO: False,
            MediaType.VIDEO: False,
            MediaType.DOCUMENT: True,
            MediaType.AUDIO: False,
            MediaType.VOICE: False,
            MediaType.GIF: False,
            MediaType.STICKER: False,
        }
    )
    chat_types: List[ChatType] = Field(default_factory=lambda: [ChatType.CHANNEL, ChatType.USER, ChatType.GROUP])
    keywords: List[str] = Field(default_factory=list)
    exclude_keywords: List[str] = Field(default_factory=list)
    chats: List[str] = Field(default_factory=lambda: ["voiacom"])
    min_file_size_kb: Optional[int] = None
    max_file_size_mb: Optional[int] = None
    download_media: bool = True
    download_path: str = "downloads"
    allowed_file_extensions: List[str] = Field(default_factory=lambda: [".txt"])
    allowed_mime_types: List[str] = Field(default_factory=lambda: ["text/plain"])
    history_enabled: bool = True
    history_limit: Optional[int] = 100

    class Settings:
        name = "scraper_settings"
