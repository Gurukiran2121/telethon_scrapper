from pydantic import BaseModel, Field
from enum import Enum
from typing import Optional
from datetime import datetime


class DownloadStatus(str, Enum):
    PENDING = "pending"
    DOWNLOADING = "downloading"
    DONE = "done"
    FAILED = "failed"


class ExtraReference(BaseModel):
    channel_name: str = Field(
        ..., 
        description="channel name where same file was found (forwarded message)"
    )
    message_id : int = Field(...,description="message id in which duplicate found")
    
    message_date: datetime = Field(
        ..., 
        description="original telegram message date"
    )
     
    


class MessageMedia(BaseModel):
    id: Optional[str] = Field(
        default=None, 
        description="unique id for the document"
    )

    chat_type: str = Field(
        ..., 
        description="chat type: group / user / channel"
    )

    chat_name: str = Field(
        ..., 
        description="channel / group / user name"
    )

    message_id: int = Field(
        ..., 
        description="telegram message id"
    )

    message_date: datetime = Field(
        ..., 
        description="original telegram message date"
    )

    scraped_at: datetime = Field(
        ..., 
        description="when scraper collected this message"
    )

    status: DownloadStatus = Field(
        default=DownloadStatus.PENDING
    )

    filename: str = Field(
        ..., 
        description="file name"
    )

    file_type: str = Field(
        ..., 
        description="file extension like txt, rar, zip"
    )

    mime_type: str = Field(
        ..., 
        description="MIME type of file"
    )

    file_size: int = Field(
        ..., 
        description="file size in bytes"
    )

    file_hash: str = Field(
        ..., 
        description="file hash for deduplication"
    )

    extra_refs: Optional[ExtraReference] = Field(
        default=None,
        description="optional reference if duplicate found"
    )

    access_hash: int = Field(
        ..., 
        description="telegram access hash"
    )