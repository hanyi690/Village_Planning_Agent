"""OSM GISProvider adapter — already WGS84, minimal transformation needed.

Wraps existing OSMProvider + OSMnx, implementing the GISProvider interface.
OSM data is already in WGS84 (EPSG:4326) — no CRS conversion needed.
"""

from __future__ import annotations

from typing import List

from app.utils.logger import get_logger

from ..base import GISProvider, GeoProviderResult
from ...models.canonical import BBox, GeoFeature

logger = get_logger(__name__)


class OSMAdapter(GISProvider):
    """Adapter wrapping OSMProvider to implement GISProvider interface.

    OSM data is already WGS84 — this adapter primarily handles:
      - Type: OSMResult → canonical GeoFeature
      - Road network extraction (village-level roads supplement Tianditu)
    """

    provider_name: str = "osm"

    def __init__(self):
        from .provider import OSMProvider
        self._provider = OSMProvider(use_cache=True)

    def is_available(self) -> bool:
        return self._provider.is_available()

    async def fetch_landuse(self, bbox: BBox) -> GeoProviderResult:
        """Fetch landuse from OSM (limited — OSM landuse tagging is sparse in rural China).

        Primary landuse should come from Tianditu. This is a fallback.
        """
        try:
            import osmnx as ox
            # OSM landuse polygons via osmnx geometries
            tags = {"landuse": True}
            gdf = ox.features_from_bbox(bbox.north, bbox.south, bbox.east, bbox.west, tags)
            if gdf is None or gdf.empty:
                return GeoProviderResult.ok([], note="No OSM landuse features found")

            features = self._gdf_to_features(gdf)
            return GeoProviderResult.ok(features, feature_count=len(features))
        except Exception as e:
            logger.warning("[OSMAdapter] fetch_landuse unavailable: %s", e)
            return GeoProviderResult.ok([], note=f"OSM landuse not available: {e}")

    async def fetch_boundary(self, village_name: str) -> GeoProviderResult:
        """Fetch village boundary from OSM (limited accuracy for Chinese villages)."""
        try:
            import osmnx as ox
            gdf = ox.geocode_to_gdf(village_name)
            if gdf is None or gdf.empty:
                return GeoProviderResult.fail(f"OSM geocoding failed for: {village_name}")

            row = gdf.iloc[0]
            geometry = row.geometry.__geo_interface__ if hasattr(row.geometry, "__geo_interface__") else {}
            feature = GeoFeature(
                geometry=geometry,
                properties={"name": village_name, "osm_id": str(row.get("osm_id", ""))},
                source_provider="osm",
            )
            return GeoProviderResult.ok(feature)
        except Exception as e:
            logger.warning("[OSMAdapter] fetch_boundary unavailable: %s", e)
            return GeoProviderResult.fail(str(e))

    async def fetch_roads(self, bbox: BBox) -> GeoProviderResult:
        """Fetch road network via OSMnx — key for village-level roads Tianditu misses.

        OSMnx 2.x bbox format: (west, south, east, north).
        """
        try:
            result = self._provider.get_road_network(
                bbox=bbox.as_tuple,
                network_type="drive",
                simplify=True,
                retain_all=False,
            )
            if not result.success or not result.data:
                return GeoProviderResult.ok([], note="No OSM roads found")

            features = self._parse_osm_roads(result)
            return GeoProviderResult.ok(features, feature_count=len(features))
        except Exception as e:
            logger.warning("[OSMAdapter] fetch_roads error: %s", e)
            return GeoProviderResult.fail(str(e))

    async def fetch_water_bodies(self, bbox: BBox) -> GeoProviderResult:
        """Fetch water features from OSM (supplemental to Tianditu HYDA/HYDL)."""
        try:
            import osmnx as ox
            tags = {"natural": ["water", "bay"], "waterway": True}
            gdf = ox.features_from_bbox(bbox.north, bbox.south, bbox.east, bbox.west, tags)
            if gdf is None or gdf.empty:
                return GeoProviderResult.ok([], note="No OSM water features found")

            features = self._gdf_to_features(gdf)
            return GeoProviderResult.ok(features, feature_count=len(features))
        except Exception as e:
            logger.debug("[OSMAdapter] fetch_water_bodies unavailable: %s", e)
            return GeoProviderResult.ok([], note=f"OSM water not available: {e}")

    # ── Parsing helpers ────────────────────────────────────────────────

    def _gdf_to_features(self, gdf) -> List[GeoFeature]:
        """Convert GeoDataFrame rows → GeoFeature list."""
        features = []
        for _, row in gdf.iterrows():
            try:
                geom = row.geometry.__geo_interface__ if hasattr(row.geometry, "__geo_interface__") else {}
                props = {k: v for k, v in row.items() if k != "geometry"}
                # Convert numpy/pandas types to Python native
                props = {k: (v.item() if hasattr(v, "item") else v) for k, v in props.items()}
                features.append(GeoFeature(
                    geometry=geom,
                    properties=props,
                    source_provider="osm",
                ))
            except Exception:
                continue  # Skip malformed features silently
        return features

    def _parse_osm_roads(self, result) -> List[GeoFeature]:
        """Parse OSMResult → GeoFeature list for roads."""
        features = []
        road_data = result.data or {}
        edges = road_data.get("edges", []) if isinstance(road_data, dict) else []

        for edge in edges:
            try:
                geom = edge.get("geometry")
                if geom is None:
                    continue
                features.append(GeoFeature(
                    geometry=geom if isinstance(geom, dict) else {},
                    properties={
                        "highway": edge.get("highway", "unclassified"),
                        "name": edge.get("name", ""),
                        "length": edge.get("length", 0),
                    },
                    source_provider="osm",
                ))
            except Exception:
                continue

        return features


__all__ = ["OSMAdapter"]
