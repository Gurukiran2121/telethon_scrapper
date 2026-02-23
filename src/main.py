import uvloop
from loguru import logger

from src.core.config import Config
from src.core.srrapper_config import ScraperConfig
from src.db.mongo.mongo_db import MongoDB
from src.services.telethon import TelethonScrapper


async def main():
    """
    initialise the mongo db
    """
    mongo = MongoDB(db_name=Config.db_name, uri=Config.db_uri)

    await mongo.init()
    logger.info("MongoDB initialized...")

    """
    initialise Telethon
    """
    telethon = TelethonScrapper(config=Config, scrapper_config=ScraperConfig)

    await telethon.run()
    logger.info("Telethon client initialized...")


if __name__ == "__main__":
    uvloop.run(main())
