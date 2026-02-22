from pydantic import BaseModel

class ConfigSchema(BaseModel):
    api_id : int
    api_hash : str
    phone_number : str
    session_name : str
    




