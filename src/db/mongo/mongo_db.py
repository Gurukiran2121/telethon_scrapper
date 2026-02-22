from src.db.base import BaseDB
from beanie import init_beanie , PydanticObjectId
from typing import Optional, List
from motor.motor_asyncio import AsyncIOMotorClient
from src.db.mongo.message_model import MongoMessageMedia
import datetime

class MongoDB(BaseDB):
    def __init__(self , uri : str , db_name : str):
        self.__client = AsyncIOMotorClient(uri)
        self.__db = self.__client[db_name]
        
    async def init(self):
        await init_beanie(
            database=self.__db,
            document_models=[MongoMessageMedia]
        )
        

    """
    create document
    """
    async def create(self, data : dict)-> MongoMessageMedia:
        doc = MongoMessageMedia(**data)
        return await doc.insert()
    
    """
    Get by id
    """
    async def get_by_id(self, id:str)->Optional[MongoMessageMedia]:
        return await MongoMessageMedia.get(PydanticObjectId(id))
    

    """
    Update the document
    """
    async def update(self, id: str, data: dict)->Optional[MongoMessageMedia]:
        doc = await MongoMessageMedia.get(PydanticObjectId(id))
        if not doc:
            return None
        
        data["updated_at"] = datetime.utcnow()
        await doc.set(data)
        return doc
    
    
    """
    delete the document from the store
    """
    async def delete(self, id : str)-> bool | None:
        doc = await MongoMessageMedia.get(PydanticObjectId(id))
        if not doc:
            return None
        
        await doc.delete()
        return True
    

    """
    to get the document based on the status
    """
    async def get_by_status(self, status:str)-> List[MongoMessageMedia]:
        return await MongoMessageMedia.find(
            MongoMessageMedia.status == status
        ).to_list()
    
    
    """
    update the document status
    """    
    async def update_status(self , id:str , status : str):
        doc = await MongoMessageMedia.get(PydanticObjectId(id))
        
        if not doc:
            return None
        
        doc.status = status
        doc.updated_at = datetime.utcnow()
        
        await doc.save()
        return doc
