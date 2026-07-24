"""Amap GISProvider adapter — CRS normalization GCJ02→WGS84.

Wraps existing Amap API calls, implementing the GISProvider interface.
GCJ02 coordinates are converted to WGS84 before returning.
"""

from __future__ import annotations

from typing import List

from app.utils.logger import get_logger

from ..base import GISProvider, GeoProviderResult
from app.modules.schema.types.canonical import BBox, GeoFeature, ProviderLandParcel

logger = get_logger(__name__)


class AmapAdapter(GISProvider):
    """Adapter wrapping Amap (高德) API to implement GISProvider interface.

    Handles:
      - CRS: GCJ02 (Mars coordinate system) → WGS84 (EPSG:4326)
      - POI search, geocoding for facility placement
      - Amap is supplemental — primary geometry comes from Tianditu/OSM
    """

    provider_name: str = "amap"

    def __init__(self):
        from .provider import AmapProvider
        self._provider = AmapProvider()

    def is_available(self) -> bool:
        return self._provider.is_available()

    async def fetch_landuse(self, bbox: BBox) -> GeoProviderResult:
        """Amap does not provide land use polygons — delegate to other providers."""
        return GeoProviderResult.ok([], note="Amap does not provide landuse data")

    async def fetch_boundary(self, village_name: str) -> GeoProviderResult:
        """Fetch administrative boundary via Amap district API.

        Amap provides district outline but at county+ level only.
        Village-level boundaries are unreliable.
        """
        try:
            result = await self._provider.get_district(village_name)
            if not result.success or not result.data:
                return GeoProviderResult.fail("Amap district boundary not found")

            district_data = result.data
            # Convert GCJ02 boundary to WGS84
            geometry = self._gcj02_geometry_to_wgs84(district_data)
            feature = GeoFeature(
                geometry=geometry,
                properties={"name": village_name, "source": "amap"},
                source_provider="amap",
            )
            return GeoProviderResult.ok(feature)
        except Exception as e:
            logger.error("[AmapAdapter] fetch_boundary error: %s", e)
            return GeoProviderResult.fail(str(e))

    async def fetch_roads(self, bbox: BBox) -> GeoProviderResult:
        """Amap does not provide road network geometry — delegate to OSM/Tianditu."""
        return GeoProviderResult.ok([], note="Amap does not provide road network data")

    async def fetch_water_bodies(self, bbox: BBox) -> GeoProviderResult:
        """Amap does not provide water body polygons."""
        return GeoProviderResult.ok([], note="Amap does not provide water body data")

    async def search_poi(
        self, keywords: str, bbox: BBox, max_results: int = 30
    ) -> GeoProviderResult:
        """Search POI within bbox — supplements facility placement.

        Returns GeoFeature list with WGS84 coordinates.
        """
        try:
            result = await self._provider.search_poi_text(
                keywords=keywords,
                region=bbox.as_tuple,
                page_size=min(max_results, 50),
            )
            if not result.success:
                return GeoProviderResult.fail(result.error or "Amap POI search failed")

            features = self._parse_poi_features(result)
            return GeoProviderResult.ok(features, poi_count=len(features))
        except Exception as e:
            logger.error("[AmapAdapter] search_poi error: %s", e)
            return GeoProviderResult.fail(str(e))

    # ── Helpers ────────────────────────────────────────────────────────

    def _gcj02_geometry_to_wgs84(self, data: dict) -> dict:
        """Convert GCJ02 geometry from Amap response to WGS84 GeoJSON."""
        from app.utils.coord_transform import gcj02_to_wgs84

        # Amap district API returns polyline string or coordinates
        polyline = data.get("polyline", "")
        if polyline:
            coords = []
            for pair in polyline.split("|"):
                for pt in pair.split(";"):
                    if "," in pt:
                        parts = pt.split(",")
                        lon, lat = gcj02_to_wgs84(float(parts[0]), float(parts[1]))
                        coords.append([lon, lat])
            return {"type": "Polygon", "coordinates": [coords]}

        return {"type": "Point", "coordinates": []}

    def _parse_poi_features(self, result) -> List[GeoFeature]:
        """Parse Amap POI results → GeoFeature list (WGS84)."""
        from app.utils.coord_transform import gcj02_to_wgs84

        features = []
        pois = result.data if isinstance(result.data, list) else []
        for poi in pois:
            try:
                gcj_lon = float(poi.get("lon", poi.get("longitude", 0)))
                gcj_lat = float(poi.get("lat", poi.get("latitude", 0)))
                wgs_lon, wgs_lat = gcj02_to_wgs84(gcj_lon, gcj_lat)

                features.append(GeoFeature(
                    geometry={"type": "Point", "coordinates": [wgs_lon, wgs_lat]},
                    properties={
                        "name": poi.get("name", ""),
                        "address": poi.get("address", ""),
                        "category": poi.get("type", poi.get("category", "")),
                    },
                    source_provider="amap",
                ))
            except (ValueError, TypeError):
                logger.debug("[AmapAdapter] Skipping malformed POI: %s", poi.get("name", ""))

        return features


__all__ = ["AmapAdapter"]
