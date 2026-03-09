from beanie import Document
from pydantic import Field
from datetime import datetime


class MongoAuthConfig(Document):
    api_id: int
    api_hash: str
    phone_number: str
    session_name: str

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "auth_config"