"""GIS Data Orchestrator — coordinates multiple providers into a unified GISDataBundle.

Strategy: Tianditu (primary) → OSM (supplemental road data) → Amap (POI enrichment)

Fallback chain:
  1. Tianditu boundary + landuse (most complete for Chinese villages)
  2. If Tianditu fails → OSM full fallback
  3. Amap POI always supplemental (not primary for geometry)

All data is normalized to WGS84 and wrapped in canonical Pydantic models
(GISDataBundle, ProviderLandParcel, GeoFeature) before returning.
"""

from __future__ import annotations

from typing import List, Optional

from app.utils.logger import get_logger

from .base import GISProvider, GeoProviderResult
from app.modules.schema.types.canonical import (
    BBox,
    GeoFeature,
    ProviderLandParcel,
    GISDataBundle,
    GISMetadata,
)

logger = get_logger(__name__)


class GISDataOrchestrator:
    """Coordinates multiple GIS providers to assemble a complete GISDataBundle.

    Usage:
        orchestrator = GISDataOrchestrator()
        orchestrator.register("tianditu", TiandituProvider())
        orchestrator.register("osm", OSMProvider())
        orchestrator.register("amap", AmapProvider())

        bundle = await orchestrator.fetch_all("金田村", bbox)
    """

    def __init__(self):
        self._providers: dict[str, GISProvider] = {}

    def register(self, provider: GISProvider) -> None:
        """Register a provider. Last registered wins for duplicate names."""
        self._providers[provider.provider_name] = provider
        logger.info("[GISDataOrchestrator] Registered provider: %s", provider.provider_name)

    def get(self, name: str) -> Optional[GISProvider]:
        return self._providers.get(name)

    @property
    def registered_providers(self) -> List[str]:
        return list(self._providers.keys())

    async def fetch_all(
        self,
        village_name: str,
        bbox: BBox,
    ) -> GISDataBundle:
        """Fetch complete GIS data for a village from all registered providers.

        Orchestration strategy:
          - Landuse: Tianditu (primary) or OSM (fallback)
          - Boundary: Tianditu (primary) or OSM (fallback)
          - Roads: Tianditu (main) + OSM (village-level supplement)
          - Water: Tianditu only
          - Annotations: Tianditu only
          - POI: Amap supplement

        Returns GISDataBundle even on partial failure — check metadata.crs_warnings.
        """
        metadata = GISMetadata(
            village_name=village_name,
            bbox_wgs84=bbox,
            provider_sources=[],
            crs_warnings=[],
        )

        boundary: Optional[GeoFeature] = None
        landuse: List[ProviderLandParcel] = []
        roads: List[GeoFeature] = []
        water_bodies: List[GeoFeature] = []
        annotations: List[GeoFeature] = []

        # ── Boundary: Tianditu primary ──
        tianditu = self._providers.get("tianditu")
        osm_provider = self._providers.get("osm")

        if tianditu and tianditu.is_available():
            result = await tianditu.fetch_boundary(village_name)
            if result.success and result.data:
                boundary = result.data
                metadata.provider_sources.append("tianditu")
            else:
                metadata.crs_warnings.append(f"tianditu boundary failed: {result.error}")
        else:
            metadata.crs_warnings.append("tianditu not available for boundary")

        # Fallback: OSM boundary
        if boundary is None and osm_provider and osm_provider.is_available():
            result = await osm_provider.fetch_boundary(village_name)
            if result.success and result.data:
                boundary = result.data
                metadata.provider_sources.append("osm")
            else:
                metadata.crs_warnings.append(f"osm boundary failed: {result.error}")

        # ── Landuse: Tianditu primary ──
        if tianditu and tianditu.is_available():
            result = await tianditu.fetch_landuse(bbox)
            if result.success:
                landuse = result.data or []
                metadata.provider_sources.append("tianditu")
            else:
                metadata.crs_warnings.append(f"tianditu landuse failed: {result.error}")
        elif osm_provider and osm_provider.is_available():
            result = await osm_provider.fetch_landuse(bbox)
            if result.success:
                landuse = result.data or []
                metadata.provider_sources.append("osm")
            else:
                metadata.crs_warnings.append(f"osm landuse failed: {result.error}")

        # ── Roads: Tianditu (main) + OSM (village supplement) ──
        if tianditu and tianditu.is_available():
            result = await tianditu.fetch_roads(bbox)
            if result.success and result.data:
                roads.extend(result.data)
                metadata.provider_sources.append("tianditu")
            else:
                metadata.crs_warnings.append(f"tianditu roads failed: {result.error}")

        if osm_provider and osm_provider.is_available():
            result = await osm_provider.fetch_roads(bbox)
            if result.success and result.data:
                osm_roads = result.data
                roads.extend(osm_roads)
                metadata.provider_sources.append("osm")
                logger.info("[GISDataOrchestrator] OSM supplement: %d village roads", len(osm_roads))
            else:
                metadata.crs_warnings.append(f"osm roads failed: {result.error}")

        # ── Water bodies: Tianditu only ──
        if tianditu and tianditu.is_available():
            result = await tianditu.fetch_water_bodies(bbox)
            if result.success and result.data:
                water_bodies = result.data
            else:
                metadata.crs_warnings.append(f"tianditu water failed: {result.error}")

        # ── Statistics ──
        metadata.parcel_count = len(landuse)
        metadata.road_count = len(roads)
        metadata.water_count = len(water_bodies)

        logger.info(
            "[GISDataOrchestrator] Fetched: %d parcels, %d roads, %d water — %d warnings",
            metadata.parcel_count,
            metadata.road_count,
            metadata.water_count,
            len(metadata.crs_warnings),
        )

        from app.modules.schema.encodings.dicts.loader import get_center
        center = get_center()
        dlbm_version = center.encoding("gbt21010").version

        return GISDataBundle(
            boundary=boundary,
            landuse=landuse,
            roads=roads,
            water_bodies=water_bodies,
            annotations=annotations,
            metadata=metadata,
            standard_version=dlbm_version,
        )


# Module-level singleton
_orchestrator: Optional[GISDataOrchestrator] = None


def get_orchestrator() -> GISDataOrchestrator:
    """Get the module-level orchestrator singleton."""
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = GISDataOrchestrator()
    return _orchestrator


__all__ = ["GISDataOrchestrator", "get_orchestrator"]
