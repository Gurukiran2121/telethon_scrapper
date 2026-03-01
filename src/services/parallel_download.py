import asyncio
import logging
import math
from typing import AsyncGenerator, List, Optional, Callable

from telethon import TelegramClient, utils
from telethon.network import MTProtoSender
from telethon.tl.alltlobjects import LAYER
from telethon.tl.functions import InvokeWithLayerRequest
from telethon.tl.functions.auth import (
    ExportAuthorizationRequest,
    ImportAuthorizationRequest,
)
from telethon.tl.functions.upload import GetFileRequest
from telethon.tl.types import InputDocumentFileLocation
from loguru import logger

from src.core.bounded_buffer import BoundedBuffer

class DownloadSender:
    """Manages a single download connection for parallel downloading."""

    def __init__(
        self,
        client: TelegramClient,
        sender: MTProtoSender,
        file: InputDocumentFileLocation,
        offset: int,
        limit: int,
        stride: int,
        count: int,
    ) -> None:
        self.sender = sender
        self.client = client
        self.request = GetFileRequest(file, offset=offset, limit=limit)
        self.stride = stride
        self.remaining = count

    async def next(self) -> Optional[bytes]:
        """Fetch the next chunk of data."""
        if not self.remaining:
            return None
        result = await self.client._call(self.sender, self.request)
        self.remaining -= 1
        self.request.offset += self.stride
        return result.bytes

    async def disconnect(self) -> None:
        """Disconnect this sender."""
        return await self.sender.disconnect()


class ParallelTransferrer:
    """Coordinates multiple parallel download connections."""

    def __init__(self, client: TelegramClient, dc_id: Optional[int] = None) -> None:
        self.client = client
        self.loop = self.client.loop
        self.dc_id = dc_id or self.client.session.dc_id
        self.auth_key = (
            None
            if dc_id and self.client.session.dc_id != dc_id
            else self.client.session.auth_key
        )
        self.senders: Optional[List[DownloadSender]] = None

    async def _cleanup(self) -> None:
        """Clean up all senders."""
        if self.senders:
            await asyncio.gather(*[sender.disconnect() for sender in self.senders])
            self.senders = None

    async def _create_download_sender(
        self,
        file: InputDocumentFileLocation,
        index: int,
        part_size: int,
        stride: int,
        part_count: int,
    ) -> DownloadSender:
        """Create a single download sender."""
        return DownloadSender(
            self.client,
            await self._create_sender(),
            file,
            index * part_size,
            part_size,
            stride,
            part_count,
        )

    async def _create_sender(self) -> MTProtoSender:
        """Create an MTProto sender with proper authentication."""
        dc = await self.client._get_dc(self.dc_id)
        sender = MTProtoSender(self.auth_key, loggers=self.client._log)
        await sender.connect(
            self.client._connection(
                dc.ip_address,
                dc.port,
                dc.id,
                loggers=self.client._log,
                proxy=self.client._proxy,
            )
        )
        if not self.auth_key:
            auth = await self.client(ExportAuthorizationRequest(self.dc_id))
            self.client._init_request.query = ImportAuthorizationRequest(
                id=auth.id, bytes=auth.bytes
            )
            req = InvokeWithLayerRequest(LAYER, self.client._init_request)
            await sender.send(req)
            self.auth_key = sender.auth_key
        return sender

    async def download(
        self,
        file: InputDocumentFileLocation,
        file_size: int,
        buffer: BoundedBuffer[bytes],
        start_offset: int = 0,
        connection_count: int = 20,
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> int:
        """
        Download file in parallel and push to a BoundedBuffer in strict order.
        """
        part_size = 1024 * 1024  # 1MB

        # Align start_offset
        if start_offset % part_size != 0:
            start_offset = (start_offset // part_size) * part_size

        total_part_count = math.ceil(file_size / part_size)
        start_part = start_offset // part_size
        remaining_parts = total_part_count - start_part

        if remaining_parts <= 0:
            buffer.close()
            return start_offset

        await self._init_download_with_offset(
            connection_count, file, remaining_parts, part_size, start_offset
        )

        bytes_downloaded = start_offset
        current_part = start_part

        try:
            sender_tasks = {}
            for i, sender in enumerate(self.senders):
                sender_tasks[i] = self.loop.create_task(sender.next())

            while current_part < total_part_count:
                sender_idx = (current_part - start_part) % len(self.senders)
                data = await sender_tasks[sender_idx]

                if data:
                    sender_tasks[sender_idx] = self.loop.create_task(
                        self.senders[sender_idx].next()
                    )

                    await buffer.put(data, len(data))
                    current_part += 1
                    bytes_downloaded += len(data)

                    if progress_callback:
                        progress_callback(bytes_downloaded, file_size)
                else:
                    break

        except Exception as e:
            logger.error(f"Ordered download failed: {e}")
            raise e
        finally:
            for task in sender_tasks.values():
                if not task.done():
                    task.cancel()
            buffer.close()
            await self._cleanup()

        return bytes_downloaded

    async def _init_download_with_offset(
        self,
        connections: int,
        file: InputDocumentFileLocation,
        part_count: int,
        part_size: int,
        start_offset: int,
    ) -> None:
        """Initialize download senders with a starting offset and staggered start."""
        minimum, remainder = divmod(part_count, connections)

        def get_part_count() -> int:
            nonlocal remainder
            if remainder > 0:
                remainder -= 1
                return minimum + 1
            return minimum

        senders = []
        for i in range(connections):
            p_count = get_part_count()
            if p_count > 0:
                # Retry loop for connection setup
                for attempt in range(3):
                    try:
                        sender = await self._create_download_sender(
                            file, i, part_size, connections * part_size, p_count
                        )
                        sender.request.offset = start_offset + (i * part_size)
                        senders.append(sender)
                        await asyncio.sleep(0.1)
                        break
                    except Exception as e:
                        if attempt == 2:
                            logger.warning(f"Sender {i + 1} failed: {e}")
                        else:
                            await asyncio.sleep(1)

        self.senders = senders
