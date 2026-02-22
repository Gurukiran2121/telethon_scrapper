from abc import ABC , abstractmethod

class BaseDB(ABC):
    
    @abstractmethod
    async def create(self , data :dict)->any:
        pass
    
    @abstractmethod
    async def get_by_id(self , id :str)->any:
        pass
    
    @abstractmethod
    async def update(self , id : str , data :dict)->any:
        pass
    
    @abstractmethod
    async def delete(self , id : str)->None:
        pass