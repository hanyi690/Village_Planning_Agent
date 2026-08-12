"""OSM connection - OpenStreetMap via OSMnx / Overpass API.

OSM is free and keyless. Rate limiting is strict on the public Overpass
endpoints, so a conservative limiter is used. The connection wraps an
osmnx configuration and an optional requests.Session for direct Overpass
queries. Availability depends on the osmnx package being installed.
"""

from __future__ import annotations

from typing import Any

import requests

from app.utils.logger import get_logger

from .base import Connection
from .rate_limiter import RateLimiter

logger = get_logger(__name__)

# Conservative QPS for public Overpass endpoints
_OSM_DEFAULT_QPS = 1.0


class OSMConnection(Connection):
    """OpenStreetMap connection (keyless, OSMnx-based)."""

    def __init__(self) -> None:
        self._rate_limiter = RateLimiter.get_instance("osm", _OSM_DEFAULT_QPS)
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": "VillagePlanningAgent/1.0",
        })
        self._cache_folder = ".osmnx_cache"

        try:
            import osmnx as ox  # noqa: F401

            self._osmnx_available = True
            ox.settings.use_cache = True
            ox.settings.log_console = False
        except ImportError:
            self._osmnx_available = False
            logger.warning("[OSMConnection] osmnx not installed; run: pip install osmnx")

    @property
    def name(self) -> str:
        return "osm"

    @property
    def rate_limiter(self) -> RateLimiter:
        return self._rate_limiter

    @property
    def timeout(self) -> int:
        return 60

    @property
    def osmnx_available(self) -> bool:
        return self._osmnx_available

    def is_configured(self) -> bool:
        """OSM is keyless; 'configured' means osmnx is importable."""
        return self._osmnx_available

    def get_session(self) -> Any:
        return self._session

    def health_check(self) -> bool:
        """Probe: check Overpass endpoint reachability."""
        try:
            self._rate_limiter.wait()
            resp = self._session.get("https://overpass-api.de/api/status", timeout=self._timeout)
            return resp.status_code == 200
        except Exception as e:
            logger.warning("[OSMConnection] health check failed: %s", e)
            return False


__all__ = ["OSMConnection"]
