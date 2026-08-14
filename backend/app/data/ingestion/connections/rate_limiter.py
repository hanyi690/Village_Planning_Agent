"""Rate limiter - thread-safe singleton per service name.

Migrated from gis/data/providers/rate_limiter.py. Each service (tianditu,
amap) has one global RateLimiter shared by all connections and drivers
targeting that service, ensuring aggregate QPS stays within provider limits.
"""

from __future__ import annotations

import asyncio
import threading
import time
from typing import Dict, Optional

from app.infrastructure.logging import get_logger

logger = get_logger(__name__)


class RateLimiter:
    """Thread-safe singleton rate limiter.

    One instance per service name. All clients of a service share the same
    limiter so the combined request rate respects the provider's QPS cap.

    Attributes:
        name: service name ('tianditu', 'amap')
        rate_limit: max requests per second (QPS)
        min_interval: minimum seconds between requests
    """

    _instances: Dict[str, "RateLimiter"] = {}
    _lock = threading.Lock()

    @classmethod
    def get_instance(cls, name: str, rate_limit: float) -> "RateLimiter":
        """Get or create the singleton limiter for a service."""
        with cls._lock:
            if name not in cls._instances:
                cls._instances[name] = RateLimiter(name, rate_limit)
                logger.info("[RateLimiter] Created: %s, QPS=%s", name, rate_limit)
            return cls._instances[name]

    @classmethod
    def get_existing_instance(cls, name: str) -> Optional["RateLimiter"]:
        """Get an existing limiter without creating one."""
        with cls._lock:
            return cls._instances.get(name)

    def __init__(self, name: str, rate_limit: float):
        self.name = name
        self.rate_limit = rate_limit
        self.min_interval = 1.0 / rate_limit if rate_limit > 0 else 0
        self._last_request_time = 0.0
        self._instance_lock = threading.Lock()

    def wait(self) -> float:
        """Block until the next request is allowed. Returns wait time in seconds."""
        if self.rate_limit <= 0:
            return 0.0

        with self._instance_lock:
            elapsed = time.time() - self._last_request_time
            wait_time = 0.0
            if elapsed < self.min_interval:
                wait_time = self.min_interval - elapsed
                time.sleep(wait_time)
            self._last_request_time = time.time()
            return wait_time

    async def async_wait(self) -> float:
        """Async wait for use in event loops."""
        if self.rate_limit <= 0:
            return 0.0

        with self._instance_lock:
            elapsed = time.time() - self._last_request_time
            wait_time = 0.0
            if elapsed < self.min_interval:
                wait_time = self.min_interval - elapsed
            self._last_request_time = time.time()

        if wait_time > 0:
            await asyncio.sleep(wait_time)
        return wait_time

    def reset(self) -> None:
        with self._instance_lock:
            self._last_request_time = 0.0

    def get_stats(self) -> Dict:
        with self._instance_lock:
            return {
                "name": self.name,
                "rate_limit": self.rate_limit,
                "min_interval": self.min_interval,
                "last_request_time": self._last_request_time,
            }


__all__ = ["RateLimiter"]
