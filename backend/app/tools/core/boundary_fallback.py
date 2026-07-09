"""Proxy boundary fallback utilities.

The merge branch calls generate_proxy_boundary_with_fallback() but did not ship
that module. This implementation creates a safe village-level polygon around the
known center, optionally sized from available GIS layer extents. It is a fallback
only; user-uploaded or API boundaries still take priority.
"""

from __future__ import annotations

import math
from typing import Any, Dict, Iterable, List, Optional, Tuple

from app.config.boundary_fallback import BoundaryFallbackConfig
from app.utils.logger import get_logger

logger = get_logger(__name__)

Coord = Tuple[float, float]


def _extract_coords_from_geometry(geometry: Dict[str, Any]) -> List[Coord]:
    geom_type = geometry.get("type")
    coords = geometry.get("coordinates") or []
    result: List[Coord] = []

    def walk(value: Any) -> None:
        if isinstance(value, (list, tuple)) and len(value) >= 2 and all(isinstance(v, (int, float)) for v in value[:2]):
            result.append((float(value[0]), float(value[1])))
            return
        if isinstance(value, (list, tuple)):
            for item in value:
                walk(item)

    if geom_type and coords:
        walk(coords)
    return result


def _extract_coords(geojson: Optional[Dict[str, Any]]) -> List[Coord]:
    if not geojson:
        return []
    if geojson.get("type") == "FeatureCollection":
        coords: List[Coord] = []
        for feature in geojson.get("features", []):
            coords.extend(_extract_coords_from_geometry(feature.get("geometry") or {}))
        return coords
    if geojson.get("type") == "Feature":
        return _extract_coords_from_geometry(geojson.get("geometry") or {})
    return _extract_coords_from_geometry(geojson)


def _circle_polygon(center: Coord, radius_m: float, points: int = 48) -> Dict[str, Any]:
    lon, lat = center
    ring: List[List[float]] = []
    for i in range(points):
        angle = 2 * math.pi * i / points
        d_lon = (radius_m / 111_320.0) * math.cos(angle)
        d_lat = (radius_m / 110_540.0) * math.sin(angle)
        ring.append([round(lon + d_lon, 7), round(lat + d_lat, 7)])
    ring.append(ring[0])
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {
                    "source": "proxy_boundary_fallback",
                    "radius_m": round(radius_m, 2),
                    "note": "自动生成的兜底边界，仅用于测试或缺少真实边界时展示",
                },
                "geometry": {"type": "Polygon", "coordinates": [ring]},
            }
        ],
    }


def _radius_from_data(center: Coord, gis_data: Dict[str, Optional[Dict[str, Any]]], config: BoundaryFallbackConfig) -> float:
    max_distance = 0.0
    cx, cy = center
    for geojson in gis_data.values():
        for lon, lat in _extract_coords(geojson):
            # good enough for fallback sizing
            dx = (lon - cx) * 111_320.0 * math.cos(math.radians(cy))
            dy = (lat - cy) * 110_540.0
            max_distance = max(max_distance, math.hypot(dx, dy))
    if max_distance <= 0:
        return config.default_radius_m
    return min(max(max_distance * 1.15, config.min_radius_m), config.max_radius_m)


def generate_proxy_boundary_with_fallback(
    center: Coord,
    village_name: str = "",
    gis_data: Optional[Dict[str, Optional[Dict[str, Any]]]] = None,
    config: Optional[BoundaryFallbackConfig] = None,
    skip_user_upload: bool = False,
) -> Dict[str, Any]:
    """Generate a proxy boundary as a final fallback.

    Returns a dict compatible with SharedGISContext expectations:
    {"success": bool, "geojson": FeatureCollection, "strategy_used": str, ...}
    """
    try:
        if not center or len(center) != 2:
            return {"success": False, "error": "invalid center", "strategy_used": "none"}
        config = config or BoundaryFallbackConfig()
        gis_data = gis_data or {}
        radius_m = _radius_from_data(center, gis_data, config)
        geojson = _circle_polygon(center, radius_m)
        geojson["features"][0]["properties"].update({"village_name": village_name})
        return {
            "success": True,
            "geojson": geojson,
            "strategy_used": "data_extent_circle" if gis_data else "default_circle",
            "radius_m": radius_m,
        }
    except Exception as exc:
        logger.error("[boundary_fallback] failed: %s", exc)
        return {"success": False, "error": str(exc), "strategy_used": "error"}
