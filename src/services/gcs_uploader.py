import asyncio
import json
import logging
import os
from typing import Dict, Any, Optional
import aiohttp
from google.cloud import storage
from google.auth.transport.requests import Request as AuthRequest
from loguru import logger

from src.core.bounded_buffer import BoundedBuffer

class ResumableGCSUploader:
    """
    Uploader that uses GCS Resumable Uploads to handle large files reliably.
    Consumes from a BoundedBuffer to ensure limited RAM usage.
    """

    def __init__(self, bucket_name: str, project_id: str, checkpoint_dir: str = ".checkpoints"):
        self.storage_client = storage.Client(project=project_id)
        self.bucket = self.storage_client.bucket(bucket_name)
        self.checkpoint_dir = checkpoint_dir
        os.makedirs(checkpoint_dir, exist_ok=True)

    def _get_checkpoint_path(self, file_id: str) -> str:
        return os.path.join(self.checkpoint_dir, f"{file_id}.json")

    def _save_checkpoint(self, file_id: str, data: Dict[str, Any]):
        path = self._get_checkpoint_path(file_id)
        with open(path, "w") as f:
            json.dump(data, f)

    def _load_checkpoint(self, file_id: str) -> Optional[Dict[str, Any]]:
        path = self._get_checkpoint_path(file_id)
        if os.path.exists(path):
            with open(path, "r") as f:
                return json.load(f)
        return None

    def _delete_checkpoint(self, file_id: str):
        path = self._get_checkpoint_path(file_id)
        if os.path.exists(path):
            os.remove(path)

    async def _get_auth_header(self) -> Dict[str, str]:
        """Get auth header for raw HTTP requests to GCS API."""
        credentials = self.storage_client._credentials
        if not credentials.valid:
            credentials.refresh(AuthRequest())
        return {"Authorization": f"Bearer {credentials.token}"}

    async def _get_session_status(self, session_url: str, total_size: int) -> Optional[int]:
        """Query GCS for the number of bytes already uploaded in the session."""
        auth_header = await self._get_auth_header()
        async with aiohttp.ClientSession(headers=auth_header) as session:
            headers = {
                "Content-Range": f"bytes */{total_size}",
                "Content-Length": "0"
            }
            try:
                async with session.put(session_url, headers=headers) as resp:
                    if resp.status == 308:
                        if "Range" in resp.headers:
                            # Format: bytes=0-123456
                            range_val = resp.headers["Range"]
                            last_byte = int(range_val.split("-")[1])
                            return last_byte + 1
                        return 0
                    elif resp.status in (200, 201):
                        return total_size
                    else:
                        text = await resp.text()
                        logger.warning(f"GCS status check failed ({resp.status}): {text}")
                        return None
            except Exception as e:
                logger.error(f"Failed to check GCS session status: {e}")
                return None

    async def get_synchronized_offset(self, file_id: str, total_size: int) -> int:
        """Get the byte offset where the upload should resume, verified by GCS."""
        checkpoint = self._load_checkpoint(file_id)
        if not checkpoint: return 0
        
        session_url = checkpoint.get("session_url")
        if not session_url: return 0
        
        gcs_bytes = await self._get_session_status(session_url, total_size)
        
        if gcs_bytes is None:
            return 0
            
        return gcs_bytes

    async def upload(
        self,
        buffer: BoundedBuffer[bytes],
        file_id: str,
        gcs_path: str,
        total_size: int,
        metadata: Dict[str, str],
        progress_callback=None,
        skip_bytes: int = 0,
        aggregation_size: int = 16 * 1024 * 1024
    ) -> str:
        """
        Upload data from buffer to GCS using a resumable session.
        """
        checkpoint = self._load_checkpoint(file_id)
        session_url = checkpoint.get("session_url") if checkpoint else None
        
        # Determine resume point
        bytes_uploaded = await self.get_synchronized_offset(file_id, total_size)
        
        # If no session or failed status, start fresh
        if not session_url or (checkpoint and bytes_uploaded == 0 and checkpoint.get("bytes_uploaded", 0) > 0):
            session_url = None
            bytes_uploaded = 0
            skip_bytes = 0

        auth_headers = await self._get_auth_header()

        if not session_url:
            init_url = f"https://storage.googleapis.com/upload/storage/v1/b/{self.bucket.name}/o?uploadType=resumable"
            init_headers = {
                **auth_headers,
                "X-Upload-Content-Type": "application/octet-stream",
                "X-Upload-Content-Length": str(total_size),
                "Content-Type": "application/json; charset=UTF-8"
            }
            body = {"name": gcs_path, "metadata": metadata}
            
            async with aiohttp.ClientSession() as session:
                async with session.post(init_url, headers=init_headers, json=body) as resp:
                    if resp.status != 200:
                        text = await resp.text()
                        raise Exception(f"Failed to initiate GCS session: {resp.status} {text}")
                    session_url = resp.headers["Location"]
                    self._save_checkpoint(file_id, {"session_url": session_url, "bytes_uploaded": 0})
        
        logger.info(f"📤 Starting GCS upload stream from {bytes_uploaded/1024/1024:.2f}MB")
        
        bytes_skipped = 0
        total_retries = 5

        async with aiohttp.ClientSession(headers=auth_headers) as session:
            current_block = bytearray()
            
            while bytes_uploaded < total_size:
                # 1. ACCUMULATE CHUNKS
                while len(current_block) < aggregation_size and bytes_uploaded + len(current_block) < total_size:
                    chunk = await buffer.get()
                    if chunk is None:
                        break # End of stream
                    
                    if bytes_skipped < skip_bytes:
                        can_skip = min(len(chunk), skip_bytes - bytes_skipped)
                        chunk = chunk[can_skip:]
                        bytes_skipped += can_skip
                        if not chunk: continue

                    current_block.extend(chunk)

                if not current_block and bytes_uploaded < total_size:
                    break

                if bytes_uploaded + len(current_block) > total_size:
                    current_block = current_block[:total_size - bytes_uploaded]
                
                block_size = len(current_block)
                if block_size == 0:
                    break

                end_byte = bytes_uploaded + block_size - 1
                content_range = f"bytes {bytes_uploaded}-{end_byte}/{total_size}"
                
                # 3. PUT BLOCK
                success = False
                for attempt in range(total_retries):
                    try:
                        headers = {
                            "Content-Range": content_range,
                            "Content-Length": str(block_size),
                            "Content-Type": "application/octet-stream"
                        }
                        async with session.put(session_url, headers=headers, data=current_block) as resp:
                            if resp.status in (200, 201, 308):
                                if resp.status in (200, 201):
                                    bytes_uploaded = total_size
                                else:
                                    bytes_uploaded += block_size
                                
                                self._save_checkpoint(file_id, {"session_url": session_url, "bytes_uploaded": bytes_uploaded})
                                if progress_callback:
                                    progress_callback(bytes_uploaded, total_size)
                                
                                current_block = bytearray()
                                success = True
                                break
                            else:
                                text = await resp.text()
                                logger.warning(f"GCS Upload Error {resp.status}: {text} (Attempt {attempt+1})")
                                if attempt == total_retries - 1:
                                    raise Exception(f"GCS Upload Final Failure: {resp.status} {text}")
                                await asyncio.sleep(min(30, 2 ** attempt))
                    except Exception as e:
                        logger.error(f"GCS Put Exception: {e} (Attempt {attempt+1})")
                        if attempt == total_retries - 1: raise e
                        await asyncio.sleep(min(30, 2 ** attempt))
                
                if not success:
                    break

        self._delete_checkpoint(file_id)
        return f"gs://{self.bucket.name}/{gcs_path}"
