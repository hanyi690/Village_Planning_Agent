"""
Coordinate Transform - WGS-84 / GCJ-02 / CGCS2000 bidirectional conversion.

Centralizes coordinate transformations previously scattered across providers:
  - amap/provider.py: gcj02_to_wgs84 (extracted here)
  - NEW: wgs84_to_gcj02 (fixes ~500m Amap API input offset)
  - NEW: cgcs2000_to_wgs84 / wgs84_to_cgcs2000 (via pyproj)

Coordinate systems:
  - WGS-84 (EPSG:4326): GPS, GeoJSON standard, Tianditu
  - GCJ-02 ("Mars coordinates"): Amap (Gaode), Tencent Maps
  - CGCS2000 (EPSG:4490): China's national geodetic system

Note: CGCS2000 and WGS-84 are often treated as equivalent in Chinese
surveying practice (sub-meter difference), but pyproj provides precise
transformation for applications requiring it.
"""

from __future__ import annotations

import math
from typing import List, Tuple

from app.infrastructure.logging import get_logger

logger = get_logger(__name__)

try:
    import pyproj
    PYPROJ_AVAILABLE = True
except ImportError:
    PYPROJ_AVAILABLE = False
    logger.warning("[coord_transform] pyproj not available, CGCS2000 conversion limited")


# ==========================================
# GCJ-02 / WGS-84 conversion constants
# ==========================================

_PI = 3.1415926535897932384626
_A = 6378245.0        # Krasovsky 1940 semi-major axis
_EE = 0.00669342162296594323  # eccentricity squared


def _out_of_china(lon: float, lat: float) -> bool:
    """Check if coordinates are outside China (no GCJ-02 offset applied)."""
    return not (73.66 < lon < 135.05 and 3.86 < lat < 53.55)


def _transform_lat(x: float, y: float) -> float:
    """GCJ-02 latitude offset calculation."""
    ret = -100.0 + 2.0 * x + 3.0 * y + 0.2 * y * y + \
          0.1 * x * y + 0.2 * math.sqrt(abs(x))
    ret += (20.0 * math.sin(6.0 * x * _PI) + 20.0 *
            math.sin(2.0 * x * _PI)) * 2.0 / 3.0
    ret += (20.0 * math.sin(y * _PI) + 40.0 *
            math.sin(y / 3.0 * _PI)) * 2.0 / 3.0
    ret += (160.0 * math.sin(y / 12.0 * _PI) + 320 *
            math.sin(y * _PI / 30.0)) * 2.0 / 3.0
    return ret


def _transform_lon(x: float, y: float) -> float:
    """GCJ-02 longitude offset calculation."""
    ret = 300.0 + x + 2.0 * y + 0.1 * x * x + \
          0.1 * x * y + 0.1 * math.sqrt(abs(x))
    ret += (20.0 * math.sin(6.0 * x * _PI) + 20.0 *
            math.sin(2.0 * x * _PI)) * 2.0 / 3.0
    ret += (20.0 * math.sin(x * _PI) + 40.0 *
            math.sin(x / 3.0 * _PI)) * 2.0 / 3.0
    ret += (150.0 * math.sin(x / 12.0 * _PI) + 300.0 *
            math.sin(x / 30.0 * _PI)) * 2.0 / 3.0
    return ret


def gcj02_to_wgs84(lon: float, lat: float, iterations: int = 3) -> Tuple[float, float]:
    """Convert GCJ-02 coordinates to WGS-84.

    Used to convert Amap (Gaode) output coordinates to WGS-84 for
    GeoJSON storage and map display.

    Uses iterative inverse method for sub-millimeter accuracy
    (vs ~1-2cm for the old double-subtraction approximation).

    Args:
        lon: GCJ-02 longitude.
        lat: GCJ-02 latitude.
        iterations: Number of refinement iterations (default 3).

    Returns:
        (wgs_lon, wgs_lat): WGS-84 coordinates.
    """
    if _out_of_china(lon, lat):
        return lon, lat

    wlon, wlat = lon, lat  # initial guess
    for _ in range(iterations):
        glon, glat = wgs84_to_gcj02(wlon, wlat)
        wlon += (lon - glon)
        wlat += (lat - glat)
    return wlon, wlat


def wgs84_to_gcj02(lon: float, lat: float) -> Tuple[float, float]:
    """Convert WGS-84 coordinates to GCJ-02.

    Used to convert internal WGS-84 coordinates to GCJ-02 before
    sending to Amap APIs. Without this conversion, Amap searches are
    offset by ~500m at Chinese latitudes.

    Args:
        lon: WGS-84 longitude.
        lat: WGS-84 latitude.

    Returns:
        (gcj_lon, gcj_lat): GCJ-02 coordinates.
    """
    if _out_of_china(lon, lat):
        return lon, lat

    dlat = _transform_lat(lon - 105.0, lat - 35.0)
    dlon = _transform_lon(lon - 105.0, lat - 35.0)
    radlat = lat / 180.0 * _PI
    magic = math.sin(radlat)
    magic = 1 - _EE * magic * magic
    sqrtmagic = math.sqrt(magic)
    dlat = (dlat * 180.0) / ((_A * (1 - _EE)) / (magic * sqrtmagic) * _PI)
    dlon = (dlon * 180.0) / (_A / sqrtmagic * math.cos(radlat) * _PI)
    mglat = lat + dlat
    mglon = lon + dlon
    return mglon, mglat


def gcj02_to_wgs84_batch(coords: List[Tuple[float, float]]) -> List[Tuple[float, float]]:
    """Batch convert GCJ-02 coordinates to WGS-84."""
    return [gcj02_to_wgs84(lon, lat) for lon, lat in coords]


def wgs84_to_gcj02_batch(coords: List[Tuple[float, float]]) -> List[Tuple[float, float]]:
    """Batch convert WGS-84 coordinates to GCJ-02."""
    return [wgs84_to_gcj02(lon, lat) for lon, lat in coords]


# ==========================================
# CGCS2000 / WGS-84 conversion (via pyproj)
# ==========================================

_CGCS2000_CRS = "EPSG:4490"
_WGS84_CRS = "EPSG:4326"

# Cached transformers (thread-safe after creation)
_cgcs2000_to_wgs84_transformer = None
_wgs84_to_cgcs2000_transformer = None


def _get_cgcs2000_to_wgs84_transformer():
    global _cgcs2000_to_wgs84_transformer
    if _cgcs2000_to_wgs84_transformer is None and PYPROJ_AVAILABLE:
        _cgcs2000_to_wgs84_transformer = pyproj.Transformer.from_crs(
            _CGCS2000_CRS, _WGS84_CRS, always_xy=True
        )
    return _cgcs2000_to_wgs84_transformer


def _get_wgs84_to_cgcs2000_transformer():
    global _wgs84_to_cgcs2000_transformer
    if _wgs84_to_cgcs2000_transformer is None and PYPROJ_AVAILABLE:
        _wgs84_to_cgcs2000_transformer = pyproj.Transformer.from_crs(
            _WGS84_CRS, _CGCS2000_CRS, always_xy=True
        )
    return _wgs84_to_cgcs2000_transformer


def cgcs2000_to_wgs84(lon: float, lat: float) -> Tuple[float, float]:
    """Convert CGCS2000 (EPSG:4490) coordinates to WGS-84 (EPSG:4326).

    For most Chinese village planning applications, CGCS2000 and WGS-84
    can be treated as equivalent (sub-meter difference). This function
    provides precise transformation when needed.

    Args:
        lon: CGCS2000 longitude.
        lat: CGCS2000 latitude.

    Returns:
        (wgs_lon, wgs_lat): WGS-84 coordinates.
    """
    if not PYPROJ_AVAILABLE:
        logger.debug("[coord_transform] pyproj unavailable, treating CGCS2000 as WGS-84")
        return lon, lat

    transformer = _get_cgcs2000_to_wgs84_transformer()
    if transformer is None:
        return lon, lat
    wgs_lon, wgs_lat = transformer.transform(lon, lat)
    return wgs_lon, wgs_lat


def wgs84_to_cgcs2000(lon: float, lat: float) -> Tuple[float, float]:
    """Convert WGS-84 (EPSG:4326) coordinates to CGCS2000 (EPSG:4490).

    Args:
        lon: WGS-84 longitude.
        lat: WGS-84 latitude.

    Returns:
        (cgcs2000_lon, cgcs2000_lat): CGCS2000 coordinates.
    """
    if not PYPROJ_AVAILABLE:
        logger.debug("[coord_transform] pyproj unavailable, treating WGS-84 as CGCS2000")
        return lon, lat

    transformer = _get_wgs84_to_cgcs2000_transformer()
    if transformer is None:
        return lon, lat
    c_lon, c_lat = transformer.transform(lon, lat)
    return c_lon, c_lat


__all__ = [
    "gcj02_to_wgs84",
    "wgs84_to_gcj02",
    "gcj02_to_wgs84_batch",
    "wgs84_to_gcj02_batch",
    "cgcs2000_to_wgs84",
    "wgs84_to_cgcs2000",
]
