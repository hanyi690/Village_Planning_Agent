"""Geometry computation helpers for spatial context.

Pure geometric operations: centroid, area, near-point search, column lookup.
These are stateless functions that operate on GeoJSON dicts or GeoDataFrames.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from app.utils.logger import get_logger

logger = get_logger(__name__)


def _compute_centroid(boundary_geojson: Dict[str, Any]) -> Optional[Tuple[float, float]]:
    """Compute centroid of boundary polygon."""
    try:
        from app.utils.geojson_utils import geojson_to_geodataframe

        gdf = geojson_to_geodataframe(boundary_geojson)
        if gdf is None or gdf.empty:
            return None
        centroid = gdf.geometry.union_all().centroid
        return (round(centroid.x, 6), round(centroid.y, 6))
    except Exception as e:
        logger.warning("[SpatialContext] Centroid computation failed: %s", e)
        return None


def _compute_total_area(geojson: Dict[str, Any]) -> float:
    """Compute total area in hectares from a GeoJSON FeatureCollection."""
    try:
        from app.utils.geojson_utils import geojson_to_geodataframe
        from app.utils.area_engine import calculate_area_ha

        gdf = geojson_to_geodataframe(geojson)
        if gdf is None or gdf.empty:
            return 0.0
        return sum(calculate_area_ha(geom) for geom in gdf.geometry)
    except Exception:
        return 0.0


def _find_column(gdf, candidates: List[str]) -> Optional[str]:
    """Find first matching column name in GeoDataFrame."""
    for col in candidates:
        if col in gdf.columns:
            return col
    return None


def _find_parcels_near_point(
    landuse_geojson: Dict[str, Any],
    center: Tuple[float, float],
    radius_m: float = 200,
) -> List[str]:
    """Find parcel BSMs near a WGS84 point within radius_m.

    Used when annotation village has no matching cluster in natural_villages.
    """
    parcel_ids = []
    try:
        from shapely.geometry import Point

        ref_point = Point(center[0], center[1])
        # Approximate degree radius at ~24N: 1 deg ~ 111km * cos(24) ~ 101km
        radius_deg = radius_m / 101000.0

        for ft in landuse_geojson.get("features", []):
            geom = ft.get("geometry", {})
            if not geom:
                continue
            from shapely.geometry import shape
            s = shape(geom)
            if s.is_empty:
                continue
            if ref_point.distance(s.centroid) < radius_deg:
                bsm = str(ft.get("properties", {}).get("BSM", "")).strip()
                if bsm:
                    parcel_ids.append(bsm)
    except Exception as e:
        logger.debug("[SpatialContext] Parcel near-point lookup failed: %s", e)
    return parcel_ids
