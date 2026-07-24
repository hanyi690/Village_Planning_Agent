"""Guangdong Tianditu connection - provincial thematic services.

Manages token (GD_TIANDITU_TOKEN, falls back to TIANDITU_API_KEY) and base
URL (GD_TIANDITU_BASE_URL). Shares the 'tianditu' rate limiter with the
national TiandituConnection because both are part of the same Tianditu
service family and share a QPS quota.
"""

from __future__ import annotations

from typing import Any

import requests

from app.core.settings import (
    GD_TIANDITU_BASE_URL,
    GD_TIANDITU_TOKEN,
    GIS_TIMEOUT,
    TIANDITU_API_KEY,
    TIANDITU_RATE_LIMIT,
)
from app.utils.logger import get_logger

from .base import Connection
from .rate_limiter import RateLimiter

logger = get_logger(__name__)


class GDTiandituConnection(Connection):
    """Guangdong Tianditu thematic services connection."""

    def __init__(self) -> None:
        self._token = GD_TIANDITU_TOKEN or TIANDITU_API_KEY
        self._base_url = GD_TIANDITU_BASE_URL
        self._timeout = GIS_TIMEOUT
        # Share the tianditu rate limiter (same service family, shared QPS)
        self._rate_limiter = RateLimiter.get_instance("tianditu", TIANDITU_RATE_LIMIT)
        self._session = requests.Session()
        self._session.headers.update({
            "Accept": "application/json",
            "User-Agent": "VillagePlanningAgent/1.0",
        })
        if not self._token:
            logger.warning("[GDTiandituConnection] GD_TIANDITU_TOKEN not configured")

    @property
    def name(self) -> str:
        return "gd_tianditu"

    @property
    def token(self) -> str:
        return self._token

    @property
    def base_url(self) -> str:
        return self._base_url

    @property
    def rate_limiter(self) -> RateLimiter:
        return self._rate_limiter

    @property
    def timeout(self) -> int:
        return self._timeout

    def is_configured(self) -> bool:
        return bool(self._token) and bool(self._base_url)

    def get_session(self) -> Any:
        return self._session

    def health_check(self) -> bool:
        """Probe: check base URL reachability."""
        if not self.is_configured():
            return False
        try:
            self._rate_limiter.wait()
            resp = self._session.head(self._base_url, timeout=self._timeout, allow_redirects=True)
            return resp.status_code < 500
        except Exception as e:
            logger.warning("[GDTiandituConnection] health check failed: %s", e)
            return False


__all__ = ["GDTiandituConnection"]
