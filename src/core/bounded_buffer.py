import asyncio
from typing import Generic, TypeVar, Optional

T = TypeVar("T")

class BoundedBuffer(Generic[T]):
    """
    A bounded buffer that provides backpressure for async producers and consumers.
    When the buffer is full, put() will block until there is space.
    When the buffer is empty, get() will block until there is data.
    """

    def __init__(self, max_size_bytes: int):
        self.max_size_bytes = max_size_bytes
        self.current_size_bytes = 0
        self.queue: asyncio.Queue[tuple[T, int]] = asyncio.Queue()
        self._closed = False
        self._put_lock = asyncio.Condition()
        self._get_lock = asyncio.Condition()

    async def put(self, item: T, size_bytes: int):
        """
        Add an item to the buffer.
        Blocks if adding the item would exceed max_size_bytes.
        """
        if self._closed:
            raise RuntimeError("Buffer is closed")

        async with self._put_lock:
            while self.current_size_bytes + size_bytes > self.max_size_bytes and self.current_size_bytes > 0:
                await self._put_lock.wait()
            
            if self._closed:
                raise RuntimeError("Buffer closed while waiting")

            await self.queue.put((item, size_bytes))
            self.current_size_bytes += size_bytes
            
            async with self._get_lock:
                self._get_lock.notify_all()

    async def get(self) -> Optional[T]:
        """
        Get an item from the buffer.
        Blocks if the buffer is empty and not closed.
        Returns None if the buffer is empty and closed.
        """
        async with self._get_lock:
            while self.queue.empty() and not self._closed:
                await self._get_lock.wait()
            
            if self.queue.empty() and self._closed:
                return None

            item, size_bytes = await self.queue.get()
            self.current_size_bytes -= size_bytes
            
            async with self._put_lock:
                self._put_lock.notify_all()
            
            return item

    def close(self):
        """Close the buffer, signaling no more items will be added."""
        self._closed = True
        
        # We need to notify all waiting tasks
        async def _notify():
            async with self._put_lock:
                self._put_lock.notify_all()
            async with self._get_lock:
                self._get_lock.notify_all()
        
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(_notify())
        except RuntimeError:
            pass

    @property
    def is_closed(self) -> bool:
        return self._closed and self.queue.empty()
