import asyncio
import os
import time
import re
from datetime import datetime
from loguru import logger
from telethon import TelegramClient, utils, types

from src.core.config import Config
from src.core.bounded_buffer import BoundedBuffer
from src.core.resource_governor import ResourceGovernor
from src.db.mongo.message_model import DownloadStatus
from src.db.mongo.mongo_db import MongoDB
from src.services.parallel_download import ParallelTransferrer
from src.services.gcs_uploader import ResumableGCSUploader

class DownloadService:
    def __init__(
        self, 
        client: TelegramClient, 
        db: MongoDB, 
        max_concurrent_files: int = 2
    ):
        self._client = client
        self._db = db
        self._max_concurrent_files = max_concurrent_files
        self._queue = asyncio.Queue()
        self._workers = []
        
        # Initialize Core Components
        self._resource_governor = ResourceGovernor()
        self._gcs_uploader = ResumableGCSUploader(
            bucket_name=Config.gcs_bucket_name,
            project_id=Config.gcs_project_id,
            checkpoint_dir=Config.checkpoint_dir
        )

    async def enqueue_download(self, message, db_doc_id: str):
        """Add a message to the download queue."""
        await self._queue.put((message, db_doc_id))
        logger.debug(f"[{message.id}] Media queued for GCS upload. Queue size: {self._queue.qsize()}")

    async def _worker(self, worker_id: int):
        """Worker that processes download tasks from the queue."""
        logger.info(f"Download worker-{worker_id} started")
        
        # Start local resource monitoring for this worker
        monitor_task = asyncio.create_task(self._resource_governor.monitor())
        
        try:
            while True:
                message, db_doc_id = await self._queue.get()
                try:
                    await self._process_pipeline(message, db_doc_id)
                except Exception as e:
                    logger.error(f"Worker-{worker_id} pipeline error: {str(e)}")
                finally:
                    self._queue.task_done()
        except asyncio.CancelledError:
            monitor_task.cancel()
            logger.info(f"Worker-{worker_id} shutting down")

    async def _process_pipeline(self, message, db_doc_id: str):
        """
        The high-performance pipeline: Telegram -> BoundedBuffer -> GCS
        """
        try:
            # 1. Prepare Metadata
            doc = await self._db.get_by_id(db_doc_id)
            if not doc: return
            
            file_name = doc.filename or "unknown"
            file_size = doc.file_size
            file_hash = doc.file_hash
            chat_name = doc.chat_name
            
            # Clean folder name for GCS
            safe_chat_name = re.sub(r"[^a-zA-Z0-9_\-]", "_", chat_name)
            
            # Simplified path: chat_name/file_name
            # If Config.gcs_root_folder is set, prepend it
            if Config.gcs_root_folder:
                gcs_path = f"{Config.gcs_root_folder.strip('/')}/{safe_chat_name}/{file_name}"
            else:
                gcs_path = f"{safe_chat_name}/{file_name}"

            # 2. Adaptive Configuration from ResourceGovernor
            adaptive_config = self._resource_governor.get_config()
            buffer_mb = adaptive_config["buffer_size_mb"]
            connections = adaptive_config["connections"]
            agg_size_mb = adaptive_config["aggregation_size_mb"]

            logger.info(
                f"[{message.id}] Starting Pipeline: {file_name} ({file_size/1024/1024:.2f} MB) | "
                f"Buf={buffer_mb}MB, Conn={connections}"
            )

            # 3. Setup Bounded Buffer (Memory Safety)
            buffer = BoundedBuffer(max_size_bytes=buffer_mb * 1024 * 1024)

            # 4. Handle Resumption (Sync GCS and Downloader)
            gcs_resume_point = await self._gcs_uploader.get_synchronized_offset(file_hash, file_size)
            
            # Align downloader to 1MB chunks (ParallelTransferrer requirement)
            part_size = 1024 * 1024
            aligned_dl_offset = (gcs_resume_point // part_size) * part_size
            skip_bytes = gcs_resume_point - aligned_dl_offset

            if gcs_resume_point > 0:
                logger.info(f"[{message.id}] Resuming from {gcs_resume_point/1024/1024:.2f}MB")

            # 5. Initialize Downloader
            dc_id, input_location = utils.get_input_location(message.media.document if hasattr(message.media, 'document') else message.media)
            downloader = ParallelTransferrer(self._client, dc_id)

            # 6. Progress Tracking
            await self._db.update_status(db_doc_id, DownloadStatus.DOWNLOADING)
            
            start_time = time.time()
            last_log = 0

            def on_progress(current, total):
                nonlocal last_log
                percent = (current / total) * 100
                if percent >= last_log + 10: # Log every 10%
                    last_log = int(percent)
                    elapsed = time.time() - start_time
                    speed = (current - gcs_resume_point) / elapsed if elapsed > 0 else 0
                    logger.info(f"[{message.id}] Progress: {percent:.1f}% | Speed: {speed/1024/1024:.2f}MB/s")

            # 7. Concurrent Download & Upload Tasks
            metadata = {
                "message_id": str(message.id),
                "file_hash": file_hash,
                "chat_name": chat_name
            }

            upload_task = asyncio.create_task(
                self._gcs_uploader.upload(
                    buffer=buffer,
                    file_id=file_hash,
                    gcs_path=gcs_path,
                    total_size=file_size,
                    metadata=metadata,
                    progress_callback=on_progress,
                    skip_bytes=skip_bytes,
                    aggregation_size=agg_size_mb * 1024 * 1024
                )
            )

            download_task = asyncio.create_task(
                downloader.download(
                    file=input_location,
                    file_size=file_size,
                    buffer=buffer,
                    start_offset=aligned_dl_offset,
                    connection_count=connections
                )
            )

            # 8. Wait for completion
            try:
                await asyncio.gather(download_task, upload_task)
                
                logger.info(f"[{message.id}] Pipeline finished: {gcs_path}")
                await self._db.update(db_doc_id, {
                    "status": DownloadStatus.DONE,
                    "gcs_path": f"gs://{Config.gcs_bucket_name}/{gcs_path}",
                    "downloaded_at": datetime.utcnow()
                })

            except Exception as e:
                download_task.cancel()
                upload_task.cancel()
                raise e

        except Exception:
            logger.exception(f"[{message.id}] Pipeline failed")
            await self._db.update_status(db_doc_id, DownloadStatus.FAILED)

    async def start(self):
        """Start the background workers."""
        for i in range(Config.max_concurrent_files):
            worker = asyncio.create_task(self._worker(i))
            self._workers.append(worker)

    async def stop(self):
        """Stop the workers gracefully."""
        for worker in self._workers:
            worker.cancel()
        
        if self._workers:
            await asyncio.gather(*self._workers, return_exceptions=True)
        self._resource_governor.stop()
        logger.info("Download Service stopped")
