"""Strict coordinate normalization for DATA/provider observations."""

from __future__ import annotations

import math
from typing import Tuple

from app.spatial.model.coord_transform import gcj02_to_wgs84


def normalize_to_wgs84(lon: float, lat: float, coord_system: str) -> Tuple[float, float, str]:
    """Normalize only a declared WGS84 or GCJ-02 coordinate contract."""

    lon_value, lat_value = float(lon), float(lat)
    if not all(math.isfinite(value) for value in (lon_value, lat_value)):
        raise ValueError("coordinates must be finite")
    if not -180.0 <= lon_value <= 180.0 or not -90.0 <= lat_value <= 90.0:
        raise ValueError("coordinates are outside WGS84 bounds")
    system = str(coord_system or "").strip().casefold().replace("-", "")
    if system == "wgs84":
        return lon_value, lat_value, "wgs84"
    if system == "gcj02":
        normalized_lon, normalized_lat = gcj02_to_wgs84(lon_value, lat_value)
        return normalized_lon, normalized_lat, "wgs84"
    raise ValueError(
        f"unsupported coordinate system {coord_system!r}; DATA refuses to guess unknown, BD09, or projected coordinates"
    )


__all__ = ["normalize_to_wgs84"]
