"""Amap connection - Gaode Maps API.

Manages credentials (AMAP_API_KEY), rate limit (AMAP_RATE_LIMIT QPS),
retries (AMAP_MAX_RETRIES), timeout (GIS_TIMEOUT). Amap returns GCJ-02
coordinates; CRS conversion to WGS-84 happens in the driver layer, not here.
"""

from __future__ import annotations

from typing import Any

import requests

from app.core.settings import (
    AMAP_API_KEY,
    AMAP_MAX_RETRIES,
    AMAP_RATE_LIMIT,
    GIS_TIMEOUT,
)
from app.utils.logger import get_logger

from .base import Connection
from .rate_limiter import RateLimiter

logger = get_logger(__name__)


class AmapConnection(Connection):
    """Gaode (Amap) API connection."""

    def __init__(self) -> None:
        self._api_key = AMAP_API_KEY
        self._rate_limit = AMAP_RATE_LIMIT
        self._max_retries = AMAP_MAX_RETRIES
        self._timeout = GIS_TIMEOUT
        self._rate_limiter = RateLimiter.get_instance("amap", self._rate_limit)
        self._session = requests.Session()
        self._session.headers.update({
            "Accept": "application/json",
            "User-Agent": "VillagePlanningAgent/1.0",
        })
        if not self._api_key:
            logger.warning("[AmapConnection] AMAP_API_KEY not configured")

    @property
    def name(self) -> str:
        return "amap"

    @property
    def api_key(self) -> str:
        return self._api_key

    @property
    def rate_limiter(self) -> RateLimiter:
        return self._rate_limiter

    @property
    def timeout(self) -> int:
        return self._timeout

    @property
    def max_retries(self) -> int:
        return self._max_retries

    def is_configured(self) -> bool:
        return bool(self._api_key)

    def get_session(self) -> Any:
        return self._session

    def health_check(self) -> bool:
        """Probe: geocode a known point."""
        if not self.is_configured():
            return False
        try:
            from app.modules.data.providers.amap.constants import GEOCODE_URL

            params = {"address": "北京", "key": self._api_key, "output": "JSON"}
            self._rate_limiter.wait()
            resp = self._session.get(GEOCODE_URL, params=params, timeout=self._timeout)
            if resp.status_code != 200:
                return False
            data = resp.json()
            return data.get("status") == "1" and data.get("infocode") == "10000"
        except Exception as e:
            logger.warning("[AmapConnection] health check failed: %s", e)
            return False


__all__ = ["AmapConnection"]
