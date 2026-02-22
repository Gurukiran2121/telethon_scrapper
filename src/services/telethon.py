import sys
import asyncio
from telethon import TelegramClient
from src.schema.telethon_schema import ConfigSchema
from loguru import logger




class TelethonScrapper():
    def __init__(self , config : ConfigSchema):
        self._config = config
        
    
    """
    function to initialize and authenticate to the telegram with mt-proto session
    """
    async def initialize(self):
        try:
            self._client = TelegramClient(session=self._config.session_name, api_id=self._config.api_id, api_hash=self._config.api_hash)
            
            await self._client.connect()
            
            if not await self._client.is_user_authorized():
                logger.info("User is not authorized")
                logger.info(f"please enter otp sent to: {self._config.phone_number}")
                
                otp = (await asyncio.to_thread(input, "Enter OTP: ")).strip()
                
                try:
                    await self._client.sign_in(phone=self._config.phone_number , code=otp)
                    logger.info("Sign in Successful")
                except Exception:
                    logger.exception("Login failed")
                    sys.exit(1)
            
            
        
        except Exception:
            logger.exception("Exception in initializing the Telethon")
            sys.exit(1)
            
        
    
    def run(self):
        self.initialize()