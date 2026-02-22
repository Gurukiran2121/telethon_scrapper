import uvloop
from src.db.mongo.mongo_db import MongoDB
from src.core.config import Config
from src.services.telethon import TelethonScrapper
from loguru import logger

async def main():
    """
    initialise the mongo db
    """
    mongo = MongoDB(
        db_name=Config.db_name,
        uri=Config.db_uri
    )
    
    await mongo.init()
    logger.info("MongoDB initialized...")
    
    
    """
    initialise Telethon
    """
    telethon = TelethonScrapper(config=Config)
    
    await telethon.initialize()
    logger.info("Telethon client initialized...")
    
    
    
    


if __name__ == "__main__":
    uvloop.run(main())
