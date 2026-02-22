from pydantic_settings import BaseSettings , SettingsConfigDict


class Settings(BaseSettings):
    
    api_id : int
    api_hash : str
    phone_number : str
    session_name : str
    db_name : str
    db_uri : str
    
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )
    
    
Config = Settings()
        