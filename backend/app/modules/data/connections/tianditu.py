"""Tianditu connection - national Tianditu API.

Manages credentials (TIANDITU_API_KEY), rate limit (TIANDITU_RATE_LIMIT QPS),
retries (TIANDITU_MAX_RETRIES), timeout (GIS_TIMEOUT). One instance is shared
by the api_vector and wmts_tile drivers targeting the national Tianditu API.
"""

from __future__ import annotations

from typing import Any

import requests

from app.core.settings import (
    GIS_TIMEOUT,
    TIANDITU_API_KEY,
    TIANDITU_MAX_RETRIES,
    TIANDITU_RATE_LIMIT,
)
from app.utils.logger import get_logger

from .base import Connection
from .rate_limiter import RateLimiter

logger = get_logger(__name__)


class TiandituConnection(Connection):
    """National Tianditu API connection."""

    def __init__(self) -> None:
        self._api_key = TIANDITU_API_KEY
        self._rate_limit = TIANDITU_RATE_LIMIT
        self._max_retries = TIANDITU_MAX_RETRIES
        self._timeout = GIS_TIMEOUT
        self._rate_limiter = RateLimiter.get_instance("tianditu", self._rate_limit)
        self._session = requests.Session()
        self._session.headers.update({
            "Accept": "application/json",
            "User-Agent": "VillagePlanningAgent/1.0",
        })
        if not self._api_key:
            logger.warning("[TiandituConnection] TIANDITU_API_KEY not configured")

    @property
    def name(self) -> str:
        return "tianditu"

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
        """Probe: geocode a known point via the V2 geocoder."""
        if not self.is_configured():
            return False
        try:
            from app.modules.data.providers.tianditu.constants import GEOCODER_URL

            params = {"ds": '{"keyWord":"北京"}', "tk": self._api_key}
            self._rate_limiter.wait()
            resp = self._session.get(GEOCODER_URL, params=params, timeout=self._timeout)
            if resp.status_code != 200:
                return False
            data = resp.json()
            return data.get("status") == 200 or bool(data.get("location"))
        except Exception as e:
            logger.warning("[TiandituConnection] health check failed: %s", e)
            return False


__all__ = ["TiandituConnection"]
