"""Tianditu connection - national Tianditu API.

Manages credentials (TIANDITU_API_KEY), rate limit (TIANDITU_RATE_LIMIT QPS),
retries (TIANDITU_MAX_RETRIES), timeout (GIS_TIMEOUT). One instance is shared
by the api_vector and wmts_tile drivers targeting the national Tianditu API.

Also provides high-level geocode / POI search methods used by DataCatalog
for schema-driven village data loading (boundary → bbox derivation).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import requests

from app.core.settings import (
    GIS_TIMEOUT,
    TIANDITU_API_KEY,
    TIANDITU_MAX_RETRIES,
    TIANDITU_RATE_LIMIT,
)
from app.infrastructure.logging import get_logger

from .base import Connection
from .rate_limiter import RateLimiter

logger = get_logger(__name__)


@dataclass
class GeocodeResult:
    """Structured geocode result from TiandituConnection."""

    success: bool
    lon: float = 0.0
    lat: float = 0.0
    formatted_address: str = ""
    error: Optional[str] = None


@dataclass
class POISearchResult:
    """Structured POI search result from TiandituConnection."""

    success: bool
    pois: List[Dict[str, Any]] = None
    total_count: int = 0
    error: Optional[str] = None

    def __post_init__(self):
        if self.pois is None:
            self.pois = []


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
            from app.data.ingestion.providers.tianditu.constants import GEOCODER_URL

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

    # ── Geocode / POI methods (for DataCatalog schema-driven loading) ──

    def geocode(self, address: str) -> GeocodeResult:
        """Geocode an address string to (lon, lat) coordinates.

        Uses the Tianditu V2 geocoder API. Goes through the connection's
        rate limiter and shared session.

        Args:
            address: Address string, e.g. "金田村" or "广东省梅州市五华县金田村".

        Returns:
            GeocodeResult with lon/lat on success, error on failure.
        """
        if not self.is_configured():
            return GeocodeResult(success=False, error="TIANDITU_API_KEY not configured")

        from app.data.ingestion.providers.tianditu.constants import GEOCODER_URL

        params = {"ds": f'{{"keyWord":"{address}"}}', "tk": self._api_key}

        for attempt in range(self._max_retries):
            self._rate_limiter.wait()
            try:
                resp = self._session.get(
                    GEOCODER_URL, params=params, timeout=self._timeout
                )
                if resp.status_code == 429:
                    import time
                    time.sleep(2 ** attempt)
                    continue
                if resp.status_code != 200:
                    return GeocodeResult(
                        success=False, error=f"HTTP {resp.status_code}"
                    )

                data = resp.json()
                location = data.get("location", {})
                if not location:
                    return GeocodeResult(
                        success=False, error=f"No location for: {address}"
                    )

                lon = float(location.get("lon", 0))
                lat = float(location.get("lat", 0))
                if lon == 0 and lat == 0:
                    return GeocodeResult(
                        success=False, error=f"Zero coordinates for: {address}"
                    )

                return GeocodeResult(
                    success=True,
                    lon=lon,
                    lat=lat,
                    formatted_address=data.get("formatted_address", address),
                )
            except Exception as e:
                logger.warning(
                    "[TiandituConnection] geocode attempt %d failed: %s",
                    attempt + 1, e,
                )
                if attempt >= self._max_retries - 1:
                    return GeocodeResult(success=False, error=str(e))

        return GeocodeResult(success=False, error="Max retries exceeded")

    def search_poi_in_region(
        self, keyword: str, region: str, page_size: int = 20
    ) -> POISearchResult:
        """Search POIs within an administrative region.

        Uses the Tianditu V2 search API with queryType=12 (region search).
        Goes through the connection's rate limiter and shared session.

        Args:
            keyword: Search keyword, e.g. "金田村".
            region: Administrative region name, e.g. "五华县".
            page_size: Max number of results.

        Returns:
            POISearchResult with pois list on success, error on failure.
        """
        if not self.is_configured():
            return POISearchResult(success=False, error="TIANDITU_API_KEY not configured")

        from app.data.ingestion.providers.tianditu.constants import SEARCH_URL

        params = {
            "postStr": f'{{"keyWord":"{keyword}","specify":"{region}","queryType":"12","start":0,"count":"{page_size}"}}',
            "type": "query",
            "tk": self._api_key,
        }

        for attempt in range(self._max_retries):
            self._rate_limiter.wait()
            try:
                resp = self._session.get(
                    SEARCH_URL, params=params, timeout=self._timeout
                )
                if resp.status_code == 429:
                    import time
                    time.sleep(2 ** attempt)
                    continue
                if resp.status_code != 200:
                    return POISearchResult(
                        success=False, error=f"HTTP {resp.status_code}"
                    )

                data = resp.json()
                # V2 API status check
                status = data.get("status")
                if isinstance(status, dict) and status.get("infocode") != 1000:
                    return POISearchResult(
                        success=False,
                        error=status.get("cndesc", "API error"),
                    )
                elif isinstance(status, (int, str)) and status not in (200, "0"):
                    return POISearchResult(
                        success=False,
                        error=data.get("message", "API error"),
                    )

                if data.get("resultType") != 1:
                    return POISearchResult(
                        success=False, error=f"No POI results for: {keyword}"
                    )

                raw_pois = data.get("pois", [])
                total = data.get("count", len(raw_pois))

                # Parse POI list (reuse provider's helper)
                from app.data.ingestion.providers.tianditu.provider import _parse_tianditu_pois
                poi_list = _parse_tianditu_pois(raw_pois)

                return POISearchResult(
                    success=True,
                    pois=poi_list,
                    total_count=total,
                )
            except Exception as e:
                logger.warning(
                    "[TiandituConnection] POI search attempt %d failed: %s",
                    attempt + 1, e,
                )
                if attempt >= self._max_retries - 1:
                    return POISearchResult(success=False, error=str(e))

        return POISearchResult(success=False, error="Max retries exceeded")


__all__ = ["TiandituConnection", "GeocodeResult", "POISearchResult"]
