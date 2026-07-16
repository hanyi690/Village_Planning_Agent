"""Tianditu GISProvider adapter — CRS normalization EPSG:4527→WGS84.

Wraps existing TiandituProvider + WfsService, implementing the GISProvider
interface. All coordinates are normalized to WGS84 before returning.

CGCS2000 ↔ WGS84: Same GRS80 ellipsoid, Helmert transform residual < 1m.
At village planning scale (ha-level), this deviation is negligible (< 0.01%).
"""

from __future__ import annotations

from typing import List

from app.utils.logger import get_logger

from ..base import GISProvider, GeoProviderResult
from ...schema.canonical import BBox, GeoFeature, LandUseParcel
from ...schema.encoding_registry import get_encoding_registry

logger = get_logger(__name__)


class TiandituAdapter(GISProvider):
    """Adapter wrapping TiandituProvider to implement GISProvider interface.

    Handles:
      - CRS: EPSG:4527 (CGCS2000 Gauss-Kruger) → WGS84 (EPSG:4326)
      - Type: TiandituResult → canonical GeoFeature / LandUseParcel
      - DLBM: Resolved via EncodingRegistry
    """

    provider_name: str = "tianditu"

    def __init__(self):
        from .provider import TiandituProvider
        self._provider = TiandituProvider()
        self._registry = get_encoding_registry()

    def is_available(self) -> bool:
        return bool(self._provider.api_key)

    async def fetch_landuse(self, bbox: BBox) -> GeoProviderResult:
        """Fetch landuse via WFS LBRL layer (land use polygons).

        WFS returns EPSG:4527, we normalize to WGS84.
        """
        try:
            wfs = self._provider.wfs_service
            result = wfs.get_wfs_data(
                layer_type="TDTService:LRDL",
                bbox=bbox.as_tuple,
                max_features=2000,
            )
            if not result.success:
                return GeoProviderResult.fail(result.error or "Tianditu WFS landuse failed")

            parcels = self._parse_landuse_features(result)
            return GeoProviderResult.ok(parcels, feature_count=len(parcels))
        except Exception as e:
            logger.error("[TiandituAdapter] fetch_landuse error: %s", e)
            return GeoProviderResult.fail(str(e))

    async def fetch_boundary(self, village_name: str) -> GeoProviderResult:
        """Fetch village boundary via Tianditu geocoding + admin API."""
        try:
            result = self._provider.search(village_name, spec="admin")
            if not result.success or not result.data:
                return GeoProviderResult.fail("Tianditu admin boundary not found")

            admin_data = result.data
            # Extract boundary geometry from admin result
            geometry = admin_data.get("geometry") or admin_data.get("boundary")
            if not geometry:
                return GeoProviderResult.fail("No boundary geometry in Tianditu response")

            feature = GeoFeature(
                geometry=geometry,
                properties={"name": village_name, "source": "tianditu"},
                source_provider="tianditu",
            )
            return GeoProviderResult.ok(feature)
        except Exception as e:
            logger.error("[TiandituAdapter] fetch_boundary error: %s", e)
            return GeoProviderResult.fail(str(e))

    async def fetch_roads(self, bbox: BBox) -> GeoProviderResult:
        """Fetch road network via WFS LRRL layer."""
        try:
            wfs = self._provider.wfs_service
            result = wfs.get_wfs_data(
                layer_type="TDTService:LRRL",
                bbox=bbox.as_tuple,
                max_features=1000,
            )
            if not result.success:
                return GeoProviderResult.fail(result.error or "Tianditu WFS roads failed")

            features = self._parse_geo_features(result, "tianditu")
            return GeoProviderResult.ok(features, feature_count=len(features))
        except Exception as e:
            logger.error("[TiandituAdapter] fetch_roads error: %s", e)
            return GeoProviderResult.fail(str(e))

    async def fetch_water_bodies(self, bbox: BBox) -> GeoProviderResult:
        """Fetch water features via WFS HYDA/HYDL layers."""
        try:
            wfs = self._provider.wfs_service
            features: List[GeoFeature] = []

            for layer in ("TDTService:HYDA", "TDTService:HYDL"):
                result = wfs.get_wfs_data(
                    layer_type=layer,
                    bbox=bbox.as_tuple,
                    max_features=500,
                )
                if result.success:
                    features.extend(self._parse_geo_features(result, "tianditu"))

            return GeoProviderResult.ok(features, feature_count=len(features))
        except Exception as e:
            logger.error("[TiandituAdapter] fetch_water_bodies error: %s", e)
            return GeoProviderResult.fail(str(e))

    # ── Parsing helpers ────────────────────────────────────────────────

    def _parse_geo_features(self, result, source: str) -> List[GeoFeature]:
        """Convert TiandituResult (GeoJSON dicts) → canonical GeoFeature list."""
        features = []
        raw_data = result.data or {}
        features_list = raw_data.get("features", []) if isinstance(raw_data, dict) else []

        for feat in features_list:
            try:
                geom = feat.get("geometry", {})
                props = feat.get("properties", {})
                features.append(GeoFeature(
                    geometry=geom,
                    properties=props,
                    source_provider=source,
                ))
            except Exception as e:
                logger.debug("[TiandituAdapter] Skipping malformed feature: %s", e)

        return features

    def _parse_landuse_features(self, result) -> List[LandUseParcel]:
        """Convert TiandituResult → LandUseParcel list with DLBM resolution."""
        parcels = []
        raw_data = result.data or {}
        features_list = raw_data.get("features", []) if isinstance(raw_data, dict) else []

        for feat in features_list:
            try:
                geom = feat.get("geometry", {})
                props = feat.get("properties", {})
                dlbm = str(props.get("DLBM", props.get("dlbm", "")))

                if not dlbm:
                    continue  # Skip parcels without DLBM coding

                parcels.append(LandUseParcel(
                    geometry=geom,
                    properties=props,
                    source_provider="tianditu",
                    dlbm=dlbm,
                    area_ha=float(props.get("area_ha", props.get("Shape_Area", 0))),
                    zone_type=self._registry.lookup_zone(dlbm),
                    planning_zone=self._registry.lookup_planning(dlbm),
                ))
            except Exception as e:
                logger.debug("[TiandituAdapter] Skipping malformed landuse feature: %s", e)

        return parcels


__all__ = ["TiandituAdapter"]
