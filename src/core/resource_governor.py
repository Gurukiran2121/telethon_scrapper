import asyncio
import logging
import os
from typing import Any, Dict, Optional

import psutil
from loguru import logger

MAX_CONNECTION = 20

class ResourceGovernor:
    """
    Monitors system resources (RAM, CPU) and provides recommendations for adaptive parallelism.
    Also acts as a watchdog to prevent OOM.
    """

    def __init__(self, ram_limit_mb: Optional[int] = None):
        self.process = psutil.Process(os.getpid())
        self._stop_event = asyncio.Event()

        # Auto-detect total RAM if no limit is provided
        total_ram_gb = psutil.virtual_memory().total / (1024**3)

        if ram_limit_mb:
            self.ram_limit_mb = ram_limit_mb
        else:
            # Smart defaults:
            # - If < 8GB: Use 25% for safety (e.g. 4GB VM -> 1GB limit)
            # - If >= 8GB: Use 15% (e.g. 18GB Mac -> ~2.7GB limit)
            if total_ram_gb < 8:
                self.ram_limit_mb = int((total_ram_gb * 1024) * 0.25)
            else:
                self.ram_limit_mb = int((total_ram_gb * 1024) * 0.15)

        logger.info(
            f"System detected: {total_ram_gb:.1f}GB RAM. Setting process limit to {self.ram_limit_mb}MB"
        )

    def get_memory_usage_mb(self) -> float:
        return self.process.memory_info().rss / (1024 * 1024)

    def get_config(self) -> Dict[str, Any]:
        """Suggest optimal buffer and connection counts based on available RAM."""
        limit_gb = self.ram_limit_mb / 1024
        buffer_size = max(64, min(512, int(limit_gb * 128)))

        # Connections: 12 per 1GB of limit.
        connections = max(10, min(MAX_CONNECTION, int(limit_gb * 12)))

        # GCS Aggregation: Target 25% of buffer, capped between 8MB and 32MB.
        aggregation = max(8, min(32, buffer_size // 4))

        config = {
            "buffer_size_mb": buffer_size,
            "connections": connections,
            "aggregation_size_mb": aggregation,
            "ram_limit_mb": self.ram_limit_mb,
        }
        return config

    def should_throttle(self) -> bool:
        """Check if current memory usage is nearing the limit."""
        usage = self.get_memory_usage_mb()
        # Throttle if > 80% usage
        return usage > (self.ram_limit_mb * 0.8)

    def is_critical(self) -> bool:
        """Check if system is in a critical RAM state."""
        usage = self.get_memory_usage_mb()
        return usage > self.ram_limit_mb

    async def monitor(self, on_critical=None):
        """Background loop to monitor resource usage."""
        logger.info(f"Monitoring resources. RAM limit: {self.ram_limit_mb}MB")
        while not self._stop_event.is_set():
            usage = self.get_memory_usage_mb()
            if self.is_critical():
                logger.warning(
                    f"CRITICAL MEMORY USAGE: {usage:.2f}MB / {self.ram_limit_mb}MB"
                )
                if on_critical:
                    await on_critical(usage)
            elif self.should_throttle():
                logger.info(f"High memory usage: {usage:.2f}MB. Throttling active.")

            await asyncio.sleep(5)

    def stop(self):
        self._stop_event.set()
