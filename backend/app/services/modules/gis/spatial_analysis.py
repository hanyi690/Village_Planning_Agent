"""Small spatial-analysis compatibility layer for GIS validators.

This module replaces legacy app.core.spatial_analysis imports used by the merged
GIS branch. It relies on geopandas/shapely when installed, and fails gracefully
when optional GIS dependencies are missing.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.utils.logger import get_logger
from .accessibility import haversine_distance
from .utils.geojson_utils import geojson_to_geodataframe, geodataframe_to_geojson

logger = get_logger(__name__)

try:
    import geopandas as gpd
    from shapely.geometry import mapping, shape
    GEOSPATIAL_AVAILABLE = True
except Exception:  # pragma: no cover - optional dependency guard
    gpd = None  # type: ignore
    mapping = None  # type: ignore
    shape = None  # type: ignore
    GEOSPATIAL_AVAILABLE = False


def _geometry_from_geojson(geometry: Dict[str, Any]):
    if not GEOSPATIAL_AVAILABLE or shape is None:
        return None
    if not geometry:
        return None
    try:
        if geometry.get("type") == "Feature":
            geometry = geometry.get("geometry") or {}
        return shape(geometry)
    except Exception as exc:
        logger.warning("[spatial_analysis] invalid geometry: %s", exc)
        return None


def calculate_buffer_zones(
    geojson: Dict[str, Any],
    buffer_distance: float = 50,
    dissolve: bool = True,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Create buffer zones around input GeoJSON features.

    Args:
        geojson: FeatureCollection/Feature geometry in EPSG:4326.
        buffer_distance: Distance in meters.
        dissolve: Merge buffers into a single geometry when true.
    """
    if not GEOSPATIAL_AVAILABLE or gpd is None:
        return {"success": False, "error": "geopandas/shapely not available"}

    try:
        gdf = geojson_to_geodataframe(geojson)
        if gdf is None or gdf.empty:
            return {"success": False, "error": "invalid or empty GeoJSON"}

        # Project to Web Mercator for meter-based buffer, then back to WGS84.
        projected = gdf.to_crs(epsg=3857)
        buffered_geom = projected.geometry.buffer(buffer_distance)
        if dissolve:
            buffered_geom = gpd.GeoSeries([buffered_geom.union_all()], crs=projected.crs)
        buffer_gdf = gpd.GeoDataFrame(geometry=buffered_geom, crs=projected.crs).to_crs(epsg=4326)
        result_geojson = geodataframe_to_geojson(buffer_gdf)
        return {
            "success": True,
            "data": {
                "geojson": result_geojson,
                "buffer_distance_m": buffer_distance,
                "feature_count": len(result_geojson.get("features", [])),
            },
        }
    except Exception as exc:
        logger.error("[spatial_analysis] buffer failed: %s", exc)
        return {"success": False, "error": str(exc)}


def _feature_collection_features(target_layer: Dict[str, Any]) -> List[Dict[str, Any]]:
    if not target_layer:
        return []
    if target_layer.get("type") == "FeatureCollection":
        return target_layer.get("features", []) or []
    if target_layer.get("type") == "Feature":
        return [target_layer]
    return [{"type": "Feature", "properties": {}, "geometry": target_layer}]


def run_spatial_query(
    query_type: str,
    geometry: Dict[str, Any],
    target_layer: Dict[str, Any],
    max_distance: Optional[float] = None,
    limit: int = 10,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Run simple spatial queries used by validators.

    Supported query_type values: contains, intersects, within, nearest.
    """
    if not GEOSPATIAL_AVAILABLE:
        return {"success": False, "error": "shapely/geopandas not available"}

    source_geom = _geometry_from_geojson(geometry)
    if source_geom is None:
        return {"success": False, "error": "invalid query geometry"}

    matches: List[Dict[str, Any]] = []
    try:
        for feature in _feature_collection_features(target_layer):
            target_geom = _geometry_from_geojson(feature.get("geometry") or {})
            if target_geom is None:
                continue

            matched = False
            distance_m: Optional[float] = None
            if query_type == "contains":
                # In planner validators this usually means target polygon contains the point.
                matched = target_geom.contains(source_geom) or target_geom.intersects(source_geom)
            elif query_type == "within":
                matched = source_geom.within(target_geom)
            elif query_type == "intersects":
                matched = source_geom.intersects(target_geom)
            elif query_type == "nearest":
                # Approximate point-to-centroid distance in meters for village-scale checks.
                sc = source_geom.centroid
                tc = target_geom.centroid
                distance_m = haversine_distance((sc.x, sc.y), (tc.x, tc.y))
                matched = max_distance is None or distance_m <= max_distance
            else:
                return {"success": False, "error": f"unsupported query_type: {query_type}"}

            if matched:
                item = {
                    "properties": feature.get("properties", {}),
                    "geometry": feature.get("geometry"),
                }
                if distance_m is not None:
                    item["distance_m"] = round(distance_m, 2)
                matches.append(item)
                if len(matches) >= limit:
                    break

        return {
            "success": True,
            "data": {
                "match_count": len(matches),
                "matches": matches,
                "query_type": query_type,
            },
        }
    except Exception as exc:
        logger.error("[spatial_analysis] query failed: %s", exc)
        return {"success": False, "error": str(exc)}


__all__ = ["calculate_buffer_zones", "geojson_to_geodataframe", "run_spatial_query"]
