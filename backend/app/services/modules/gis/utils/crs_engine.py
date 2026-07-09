"""
CRS Engine - Coordinate Reference System transformation engine.

Replaces scattered EPSG:3857 usage with CGCS2000 Gauss-Kruger 3-degree zones
for accurate area and distance calculations in Chinese village planning.

Key improvement: EPSG:3857 (Web Mercator) inflates areas by 15-35% at Chinese
latitudes (20-40N). CGCS2000 Gauss-Kruger projection keeps area distortion
below 0.03% within each 3-degree zone.
"""

import math
from typing import Optional, Tuple

from app.utils.logger import get_logger

logger = get_logger(__name__)

try:
    import geopandas as gpd
    import pyproj
    GEOPANDAS_AVAILABLE = True
except ImportError:
    GEOPANDAS_AVAILABLE = False
    logger.warning("[crs_engine] geopandas/pyproj not available, CRS operations limited")

# CGCS2000 geographic CRS (EPSG:4490) — China's national geodetic system
CGCS2000_GEOGRAPHIC = "EPSG:4490"
# WGS-84 geographic CRS (EPSG:4326) — GeoJSON standard
WGS84_GEOGRAPHIC = "EPSG:4326"
# Web Mercator (EPSG:3857) — kept as fallback only
WEB_MERCATOR = "EPSG:3857"

# CGCS2000 Gauss-Kruger 3-degree zones: EPSG:4491 (zone 13, 78E) to EPSG:4554 (zone 22, 132E)
# Zone number n -> central meridian = 3n degrees East
# Zone number n -> EPSG code = 4490 + n
_GK3_ZONE_MIN = 13
_GK3_ZONE_MAX = 45  # extends beyond China for edge cases


def get_metric_crs(lon: float) -> str:
    """Select CGCS2000 / Gauss-Kruger 3-degree zone EPSG code for a given longitude.

    Args:
        lon: Longitude in degrees (WGS-84).

    Returns:
        EPSG code string, e.g. "EPSG:4547" for Meizhou (116E, zone 39).
    """
    zone_number = int(round((lon + 1.5) / 3.0))
    zone_number = max(_GK3_ZONE_MIN, min(_GK3_ZONE_MAX, zone_number))
    epsg_code = 4490 + zone_number
    return f"EPSG:{epsg_code}"


def get_zone_central_meridian(lon: float) -> float:
    """Return the central meridian of the 3-degree zone containing lon."""
    zone_number = int(round((lon + 1.5) / 3.0))
    return zone_number * 3.0


def project_to_metric(
    gdf: "gpd.GeoDataFrame",
    lon: Optional[float] = None,
) -> "gpd.GeoDataFrame":
    """Project a GeoDataFrame to the appropriate CGCS2000 metric CRS.

    Replaces scattered gdf.to_crs("EPSG:3857") calls with a single
    function that automatically selects the correct projection zone.

    Args:
        gdf: GeoDataFrame in EPSG:4326 (WGS-84).
        lon: Override longitude for zone selection. If None, uses the
             centroid of the geometry union.

    Returns:
        GeoDataFrame in the selected CGCS2000 Gauss-Kruger projection.
    """
    if not GEOPANDAS_AVAILABLE:
        raise RuntimeError("geopandas required for project_to_metric")

    if lon is None:
        try:
            lon = gdf.geometry.union_all().centroid.x
        except Exception:
            lon = 116.0  # fallback: central China

    target_crs = get_metric_crs(lon)
    logger.debug(f"[crs_engine] Projecting to {target_crs} (lon={lon:.2f})")
    return gdf.to_crs(target_crs)


def project_to_wgs84(gdf: "gpd.GeoDataFrame") -> "gpd.GeoDataFrame":
    """Project a GeoDataFrame back to WGS-84 (EPSG:4326) for GeoJSON output."""
    if not GEOPANDAS_AVAILABLE:
        raise RuntimeError("geopandas required for project_to_wgs84")
    return gdf.to_crs(WGS84_GEOGRAPHIC)


def project_geometry(
    geom,
    from_crs: str,
    to_crs: str,
) -> object:
    """Project a single Shapely geometry between CRSes.

    Uses pyproj.Transformer with always_xy=True for consistent (lon, lat) ordering.

    Args:
        geom: Shapely geometry object.
        from_crs: Source CRS EPSG string.
        to_crs: Target CRS EPSG string.

    Returns:
        Transformed Shapely geometry.
    """
    from shapely.ops import transform as shapely_transform

    transformer = pyproj.Transformer.from_crs(
        from_crs, to_crs, always_xy=True
    )
    return shapely_transform(transformer.transform, geom)


def project_geometries_batch(
    geometries: list,
    from_crs: str,
    to_crs: str,
) -> list:
    """Project a batch of Shapely geometries efficiently using GeoSeries.

    Much faster than per-geometry transformation for large datasets.

    Args:
        geometries: List of Shapely geometry objects.
        from_crs: Source CRS EPSG string.
        to_crs: Target CRS EPSG string.

    Returns:
        List of transformed Shapely geometry objects.
    """
    if not GEOPANDAS_AVAILABLE:
        raise RuntimeError("geopandas required for batch projection")

    gs = gpd.GeoSeries(geometries, crs=from_crs)
    projected = gs.to_crs(to_crs)
    return projected.tolist()


def meters_to_degrees_lon(meters: float, lat: float) -> float:
    """Convert meters to degrees of longitude at a given latitude.

    Uses the WGS-84 ellipsoid approximation.
    At the equator, 1 degree ≈ 111,320 m.
    At lat 30N (central China), 1 degree ≈ 96,488 m.
    """
    return meters / (111320.0 * math.cos(math.radians(lat)))


def meters_to_degrees_lat(meters: float) -> float:
    """Convert meters to degrees of latitude.

    Approximately 110,540 m per degree (varies slightly with latitude).
    """
    return meters / 110540.0


def degrees_to_meters_lon(degrees: float, lat: float) -> float:
    """Convert degrees of longitude to meters at a given latitude."""
    return degrees * 111320.0 * math.cos(math.radians(lat))


def degrees_to_meters_lat(degrees: float) -> float:
    """Convert degrees of latitude to meters."""
    return degrees * 110540.0


def _project_point(lon: float, lat: float, target_crs: str) -> Tuple[float, float]:
    """Project a single WGS-84 (lon, lat) point to target CRS.

    Internal helper used by coord_utils.transform_coord.
    """
    if not GEOPANDAS_AVAILABLE:
        return (lon, lat)
    from shapely.geometry import Point
    gs = gpd.GeoSeries([Point(lon, lat)], crs=WGS84_GEOGRAPHIC)
    projected = gs.to_crs(target_crs)
    pt = projected.iloc[0]
    return (pt.x, pt.y)
