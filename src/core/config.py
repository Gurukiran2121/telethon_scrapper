from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field

class Settings(BaseSettings):
    api_id: int
    api_hash: str
    phone_number: str
    session_name: str
    db_name: str
    db_uri: str
    
    # GCS Configuration
    gcs_bucket_name: str
    gcs_project_id: str
    gcs_root_folder: str = ""
    checkpoint_dir: str = ".checkpoints"
    
    # Scalability Configuration
    max_concurrent_files: int = 2  # How many files to download at once
    workers_per_file: int = 5     # How many background workers in DownloadService

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

Config = Settings()
