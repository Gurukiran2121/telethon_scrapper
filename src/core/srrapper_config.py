from enum import Enum
from typing import Dict, List

from pydantic import BaseModel, Field


class MediaType(str, Enum):
    PHOTO = "photo"
    VIDEO = "video"
    DOCUMENT = "document"
    AUDIO = "audio"
    VOICE = "voice"
    GIF = "gif"
    STICKER = "sticker"


class ChatType(str, Enum):
    CHANNEL = "channel"
    GROUP = "group"
    USER = "user"


class ScraperSettings(BaseModel):
    media_enabled: bool = Field(
        default=True, description="bool to define engine to scrap media"
    )

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

    chat_types: List[ChatType] = Field(default_factory=lambda: [ChatType.CHANNEL])

    keywords: List[str] = Field(default_factory=list)
    exclude_keywords: List[str] = Field(default_factory=list)
    chats: List[str] = Field(default_factory=lambda: ["voiacom"])

    min_file_size_kb: int | None = None
    max_file_size_mb: int | None = None

    download_media: bool = True
    download_path: str = "downloads"

    allowed_file_extensions: List[str] = Field(default_factory=lambda: [".txt"])
    allowed_mime_types: List[str] = Field(default_factory=lambda: ["text/plain"])


ScraperConfig = ScraperSettings()
