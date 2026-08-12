"""
Area Engine - Unified area calculation with CGCS2000 projection.

Replaces EPSG:3857-based area calculations that inflate areas by 15-35%
at Chinese latitudes. Uses CGCS2000 Gauss-Kruger 3-degree zones via
crs_engine for distortion <0.03%.

All outputs in hectares (ha) — the national standard unit for Chinese
village planning (GB/T 21010).
"""

from __future__ import annotations

import math
from typing import Any, List, Optional, Sequence

from app.infrastructure.logging import get_logger

logger = get_logger(__name__)

try:
    import geopandas as gpd
    import pyproj
    GEOPANDAS_AVAILABLE = True
except ImportError:
    GEOPANDAS_AVAILABLE = False
    logger.warning("[area_engine] geopandas/pyproj not available, area calculations limited")

from .crs_engine import get_metric_crs, project_to_metric


def calculate_area_ha(
    geometry: Any,
    lon: Optional[float] = None,
    lat: Optional[float] = None,
    metric_crs: Optional[str] = None,
) -> float:
    """Calculate area of a Shapely geometry in hectares.

    Uses CGCS2000 Gauss-Kruger projection for accuracy. Falls back to
    spherical approximation with cos(lat) correction when geopandas is
    unavailable.

    Args:
        geometry: Shapely geometry object (Polygon/MultiPolygon).
        lon: Longitude for zone selection. If None, uses geometry centroid.
        lat: Latitude for fallback cos(lat) correction. If None, uses centroid.
        metric_crs: If provided and geometry is already in this metric CRS,
                    compute area directly without reprojection.

    Returns:
        Area in hectares (1 ha = 10,000 m²).
    """
    if geometry is None or geometry.is_empty:
        return 0.0

    try:
        if GEOPANDAS_AVAILABLE:
            # Fast path: geometry already in a metric CRS
            if metric_crs is not None:
                return geometry.area / 10_000.0

            gdf = gpd.GeoDataFrame([{"geometry": geometry}], crs="EPSG:4326")
            if lon is None:
                try:
                    lon = geometry.centroid.x
                except Exception:
                    lon = 116.0
            gdf_proj = project_to_metric(gdf, lon=lon)
            area_m2 = gdf_proj.geometry.area.sum()
            return area_m2 / 10_000.0
    except Exception as e:
        logger.warning(f"[area_engine] Projected area failed, using fallback: {e}")

    return _area_ha_fallback(geometry, lat=lat)


def calculate_area_km2(
    geometry: Any,
    lon: Optional[float] = None,
    lat: Optional[float] = None,
) -> float:
    """Calculate area in square kilometers.

    Args:
        geometry: Shapely geometry object.
        lon: Longitude for zone selection.
        lat: Latitude for fallback correction.

    Returns:
        Area in km².
    """
    return calculate_area_ha(geometry, lon=lon, lat=lat) / 100.0


def calculate_areas_batch_ha(
    geometries: Sequence[Any],
    lon: Optional[float] = None,
) -> List[float]:
    """Calculate areas for multiple geometries in hectares.

    Single CRS transformation for all geometries — much faster than
    per-geometry projection.

    Args:
        geometries: Sequence of Shapely geometry objects.
        lon: Longitude for zone selection. If None, uses union centroid.

    Returns:
        List of areas in hectares.
    """
    if not geometries:
        return []

    try:
        if GEOPANDAS_AVAILABLE:
            gdf = gpd.GeoDataFrame(
                {"geometry": list(geometries)}, crs="EPSG:4326"
            )
            gdf_proj = project_to_metric(gdf, lon=lon)
            return [a / 10_000.0 for a in gdf_proj.geometry.area.values]
    except Exception as e:
        logger.warning(f"[area_engine] Batch projection failed, using fallback: {e}")

    return [_area_ha_fallback(g) for g in geometries]


def calculate_areas_batch_km2(
    geometries: Sequence[Any],
    lon: Optional[float] = None,
) -> List[float]:
    """Calculate areas for multiple geometries in km²."""
    ha_list = calculate_areas_batch_ha(geometries, lon=lon)
    return [ha / 100.0 for ha in ha_list]


def _area_ha_fallback(
    geometry: Any,
    lat: Optional[float] = None,
) -> float:
    """Spherical approximation fallback with cos(lat) correction.

    Replaces the incorrect `area * 111 * 111` which ignores latitude.
    At lat 25N (southern China), cos(25°) = 0.906 → old method overestimates by 10%.
    At lat 40N (northern China), cos(40°) = 0.766 → old method overestimates by 30%.
    """
    if geometry is None or geometry.is_empty:
        return 0.0

    try:
        area_sq_deg = geometry.area
        if lat is None:
            try:
                lat = geometry.centroid.y
            except Exception:
                lat = 30.0  # central China default

        # 1 degree latitude ≈ 110,540 m (varies slightly)
        # 1 degree longitude ≈ 111,320 * cos(lat) m
        m_per_deg_lat = 110_540.0
        m_per_deg_lon = 111_320.0 * math.cos(math.radians(lat))

        area_m2 = area_sq_deg * m_per_deg_lat * m_per_deg_lon
        return area_m2 / 10_000.0
    except Exception:
        return 0.0


__all__ = [
    "calculate_area_ha",
    "calculate_area_km2",
    "calculate_areas_batch_ha",
    "calculate_areas_batch_km2",
]
