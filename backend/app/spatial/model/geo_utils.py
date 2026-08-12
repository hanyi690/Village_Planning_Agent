"""
Geo Utilities - 地理计算工具函数

提供距离计算、面积计算等地理计算工具。
"""

import math
from typing import Tuple, List, Any, Optional, Iterable

from shapely.geometry import mapping
from shapely.ops import unary_union
from shapely.validation import make_valid

from app.infrastructure.logging import get_logger

logger = get_logger(__name__)

# Check geopandas availability for area calculations
try:
    import geopandas as gpd
    GEOPANDAS_AVAILABLE = True
except ImportError:
    GEOPANDAS_AVAILABLE = False
    logger.warning("[geo_utils] geopandas not available, area calculations limited")


def haversine_distance(coord1: Tuple[float, float], coord2: Tuple[float, float]) -> float:
    """
    计算两点之间的 Haversine 距离（米）

    Args:
        coord1: 第一个点的坐标 (lon, lat)
        coord2: 第二个点的坐标 (lon, lat)

    Returns:
        两点之间的距离（米）
    """
    lon1, lat1 = coord1
    lon2, lat2 = coord2

    R = 6371000  # 地球半径（米）

    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = math.sin(delta_phi / 2) ** 2 + \
        math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return R * c


def safe_unary_union(geometries: Iterable) -> Any:
    """unary_union with make_valid() to prevent TopologyException.

    Invalid geometries (self-intersections, side-location conflicts)
    cause shapely unary_union to raise GEOSException. This helper
    sanitizes each geometry before union.

    Args:
        geometries: Iterable of Shapely geometry objects.

    Returns:
        Merged geometry (Polygon or MultiPolygon), or empty Polygon if all fail.
    """
    from shapely.geometry import GeometryCollection

    valid = []
    for g in geometries:
        if g is None or g.is_empty:
            continue
        if not g.is_valid:
            try:
                g = g.buffer(0)
            except Exception:
                try:
                    g = make_valid(g)
                except Exception:
                    continue
        if g is not None and not g.is_empty:
            # make_valid may return GeometryCollection with mixed dimensions
            if g.geom_type == "GeometryCollection":
                areal = [p for p in g.geoms if p.area > 0]
                if areal:
                    g = unary_union(areal) if len(areal) > 1 else areal[0]
                else:
                    continue
            if g is not None and not g.is_empty:
                valid.append(g)

    if not valid:
        return GeometryCollection()

    try:
        return unary_union(valid)
    except Exception:
        # Second attempt: buffer(0) each geometry then union
        buffered = []
        for g in valid:
            try:
                bg = g.buffer(0)
                if bg is not None and not bg.is_empty:
                    buffered.append(bg)
            except Exception:
                continue
        if not buffered:
            return GeometryCollection()
        return unary_union(buffered)


def safe_geo_series_union(geo_series: "gpd.GeoSeries") -> Any:
    """Safe replacement for GeoSeries.union_all() with geometry validation.

    Fixes invalid geometries before union to prevent TopologyException.

    Args:
        geo_series: GeoPandas GeoSeries.

    Returns:
        Merged geometry (Polygon or MultiPolygon), or empty Point.
    """
    from shapely.validation import make_valid
    from shapely.geometry import Point

    valid = []
    for g in geo_series:
        if g is None or g.is_empty:
            continue
        if not g.is_valid:
            try:
                g = g.buffer(0)
            except Exception:
                try:
                    g = make_valid(g)
                except Exception:
                    continue
        # make_valid may return GeometryCollection with mixed dimensions
        # (e.g., Polygon + LineString); extract only 2D (areal) parts
        if g is not None and not g.is_empty:
            if g.geom_type == "GeometryCollection":
                from shapely.ops import unary_union as _uu
                areal = [p for p in g.geoms if p.area > 0]
                if areal:
                    g = _uu(areal) if len(areal) > 1 else areal[0]
                else:
                    continue
            if g is not None and not g.is_empty and g.area > 0:
                valid.append(g)

    if not valid:
        return Point()

    try:
        from shapely.ops import unary_union as _unary_union
        return _unary_union(valid)
    except Exception:
        buffered = []
        for g in valid:
            try:
                bg = g.buffer(0)
                if bg is not None and not bg.is_empty:
                    buffered.append(bg)
            except Exception:
                continue
        if not buffered:
            return Point()
        from shapely.ops import unary_union as _unary_union
        return _unary_union(buffered)


def calculate_area_km2(geometry: Any) -> float:
    """Calculate area of a geometry in km² (delegates to area_engine).

    Args:
        geometry: Shapely geometry object.

    Returns:
        Area in km².
    """
    from .area_engine import calculate_area_km2 as _calc_km2
    return _calc_km2(geometry)


def calculate_areas_batch(geometries: List[Any]) -> List[float]:
    """Calculate areas for multiple geometries in km² (delegates to area_engine).

    Args:
        geometries: Shapely geometry objects.

    Returns:
        List of areas in km².
    """
    from .area_engine import calculate_areas_batch_km2
    return calculate_areas_batch_km2(geometries)


__all__ = ['haversine_distance', 'calculate_area_km2', 'calculate_areas_batch', 'safe_unary_union', 'safe_geo_series_union']