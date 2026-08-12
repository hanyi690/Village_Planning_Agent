"""
GeoJSON Utilities - GeoJSON 转换工具函数

提供 GeoJSON 与 GeoDataFrame 之间的转换工具。
"""

import json
from typing import Dict, Any, Optional, List

from app.infrastructure.logging import get_logger

logger = get_logger(__name__)

# Check geopandas availability
try:
    import geopandas as gpd
    GEOPANDAS_AVAILABLE = True
except ImportError:
    GEOPANDAS_AVAILABLE = False
    logger.warning("[geojson_utils] geopandas/shapely not available")


def geojson_to_geodataframe(geojson: Dict[str, Any]) -> Optional["gpd.GeoDataFrame"]:
    """
    将 GeoJSON FeatureCollection 转换为 GeoDataFrame

    Args:
        geojson: GeoJSON FeatureCollection 字典

    Returns:
        GeoDataFrame 或 None（转换失败时）
    """
    if not GEOPANDAS_AVAILABLE:
        return None

    try:
        import shapely.geometry

        features = geojson.get("features", [])
        if not features:
            return None

        geometries = []
        properties = []

        for feature in features:
            geom_data = feature.get("geometry", {})
            props = feature.get("properties", {})

            try:
                geom_obj = shapely.geometry.shape(geom_data)
                geometries.append(geom_obj)
            except Exception as e:
                logger.warning(f"[geojson_utils] Failed to create geometry: {e}")
                geometries.append(None)

            properties.append(props)

        # 过滤掉 None 几何对象
        valid_indices = [i for i, g in enumerate(geometries) if g is not None]
        if not valid_indices:
            return None

        geometries = [geometries[i] for i in valid_indices]
        properties = [properties[i] for i in valid_indices]

        gdf = gpd.GeoDataFrame(properties, geometry=geometries)
        if gdf.crs is None:
            gdf.set_crs("EPSG:4326", inplace=True)

        return gdf

    except Exception as e:
        logger.error(f"[geojson_utils] GeoJSON conversion failed: {e}")
        return None


def geodataframe_to_geojson(gdf: "gpd.GeoDataFrame") -> Dict[str, Any]:
    """
    将 GeoDataFrame 转换为 GeoJSON FeatureCollection

    Args:
        gdf: GeoDataFrame

    Returns:
        GeoJSON FeatureCollection 字典
    """
    features = []

    for idx, row in gdf.iterrows():
        geometry = row.geometry
        if geometry is None:
            continue

        geom_type = geometry.geom_type
        coords = _get_geometry_coords(geometry)

        props = {k: v for k, v in row.items() if k != 'geometry'}
        # 转换不可序列化的值
        for k, v in props.items():
            if hasattr(v, '__iter__') and not isinstance(v, (str, list, dict)):
                props[k] = list(v) if hasattr(v, '__iter__') else str(v)

        feature = {
            "type": "Feature",
            "properties": props,
            "geometry": {
                "type": geom_type,
                "coordinates": coords
            }
        }
        features.append(feature)

    return {"type": "FeatureCollection", "features": features}


def _get_geometry_coords(geometry) -> List:
    """Extract coordinates from a Shapely geometry via __geo_interface__."""
    return geometry.__geo_interface__["coordinates"]


def reduce_coordinate_precision(geojson: Dict[str, Any], decimals: int = 6) -> Dict[str, Any]:
    """Reduce coordinate precision in a GeoJSON FeatureCollection.

    MapLibre GL JS official best practice: 6 decimal places ≈ 0.1m precision,
    sufficient for village-level planning. Reduces 15-17 decimal places
    (atomic scale) to practical precision, cutting data size ~40-50%.

    Args:
        geojson: GeoJSON FeatureCollection dict
        decimals: Number of decimal places to keep (default 6)

    Returns:
        GeoJSON with rounded coordinates (mutated in-place for performance)
    """
    features = geojson.get("features", [])
    for feature in features:
        geom = feature.get("geometry")
        if not geom:
            continue
        geom["coordinates"] = _round_coords(geom["coordinates"], decimals)
    return geojson


def _round_coords(coords, decimals: int):
    """Recursively round coordinate values."""
    if not coords:
        return coords
    if isinstance(coords[0], (int, float)):
        return [round(c, decimals) for c in coords]
    return [_round_coords(c, decimals) for c in coords]


def simplify_geojson(geojson: Dict[str, Any], tolerance: float = 0.00005) -> Dict[str, Any]:
    """Simplify GeoJSON geometries using Douglas-Peucker algorithm.

    Args:
        geojson: GeoJSON FeatureCollection dict
        tolerance: Simplification tolerance in degrees (~0.00005° ≈ 5m)

    Returns:
        GeoJSON with simplified geometries (mutated in-place)
    """
    if not GEOPANDAS_AVAILABLE:
        return geojson

    try:
        from shapely.geometry import shape, mapping
        features = geojson.get("features", [])
        for feature in features:
            geom = feature.get("geometry")
            if not geom:
                continue
            geom_type = geom.get("type", "")
            if geom_type in ("Point", "MultiPoint"):
                continue
            try:
                shapely_geom = shape(geom)
                simplified = shapely_geom.simplify(tolerance, preserve_topology=True)
                feature["geometry"] = mapping(simplified)
            except Exception:
                pass
        return geojson
    except Exception as e:
        logger.warning(f"[geojson_utils] simplify_geojson failed: {e}")
        return geojson


def build_parcel_index(
    landuse_geojson: Dict[str, Any],
    zone_type_fn=None,
) -> tuple:
    """Build parcel index from landuse GeoJSON for zone allocation.

    Extracts BSM/DLBM/area from landuse features and resolves zone types.
    Uses composite_key (BSM_DLBM_SHAPEArea) because BSM is NOT unique —
    80 BSMs have 2 different DLBM codes, and 38 BSM+DLBM pairs have
    multiple features with different geometries/areas.

    Args:
        landuse_geojson: GeoJSON FeatureCollection of land use parcels
        zone_type_fn: Optional callable(dlbm: str) -> str for zone type resolution

    Returns:
        Tuple of (parcel_db: dict, duplicate_bsms: set)
        parcel_db maps composite_key -> {area_ha, dlbm, bsm_bare, current_zone, feature}
    """
    from app.infrastructure.logging import get_logger as _get_logger
    _logger = _get_logger(__name__)

    features = landuse_geojson.get("features", [])
    parcel_db: Dict[str, Dict[str, Any]] = {}
    duplicate_bsms: set = set()
    seen_bsms: set = set()

    for ft in features:
        props = ft.get("properties", {})
        bsm = str(props.get("BSM") or props.get("bsm") or "").strip()
        dlbm = str(props.get("DLBM") or props.get("dlbm") or "").strip()
        if not bsm:
            continue
        shape_area = (
            props.get("SHAPE_Area")
            or props.get("Shape_Area")
            or props.get("area_sqm")
            or 0
        )
        composite_key = f"{bsm}_{dlbm}_{int(shape_area)}"
        if bsm in seen_bsms:
            duplicate_bsms.add(bsm)
        seen_bsms.add(bsm)
        area = (props.get("DLMJ") or props.get("area_sqm") or shape_area) / 10000
        current_zone = zone_type_fn(dlbm) if zone_type_fn else ""
        parcel_db[composite_key] = {
            "area_ha": area,
            "dlbm": dlbm,
            "bsm_bare": bsm,
            "current_zone": current_zone,
            "feature": ft,
        }

    if duplicate_bsms:
        _logger.debug(
            f"[ParcelIndex] {len(duplicate_bsms)} BSMs with multiple DLBM codes "
            f"({len(parcel_db)} total parcels)"
        )

    return parcel_db, duplicate_bsms


__all__ = [
    'geojson_to_geodataframe',
    'geodataframe_to_geojson',
    'reduce_coordinate_precision',
    'simplify_geojson',
    'build_parcel_index',
]
