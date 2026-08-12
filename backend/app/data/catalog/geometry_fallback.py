"""Legacy geometry fallback helpers for the data catalog.

Coordinate extraction and bounding-box construction used when deriving a
bounding box from boundary geometry or geocoding a village name.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from app.data.model.canonical import BBox


def _extract_coords(geometry: Dict[str, Any], out: List[Tuple[float, float]]) -> None:
    """Recursively extract (lon, lat) coordinate pairs from a GeoJSON geometry."""
    geom_type = geometry.get("type", "")
    coords = geometry.get("coordinates", [])

    if geom_type == "Point":
        if len(coords) >= 2:
            out.append((coords[0], coords[1]))
    elif geom_type in ("LineString", "MultiPoint"):
        for c in coords:
            if len(c) >= 2:
                out.append((c[0], c[1]))
    elif geom_type in ("Polygon", "MultiLineString"):
        for ring in coords:
            for c in ring:
                if len(c) >= 2:
                    out.append((c[0], c[1]))
    elif geom_type == "MultiPolygon":
        for polygon in coords:
            for ring in polygon:
                for c in ring:
                    if len(c) >= 2:
                        out.append((c[0], c[1]))


def _derive_bbox_from_boundary(geojson: Dict[str, Any]) -> Optional[BBox]:
    """Derive BBox from boundary GeoJSON geometry.

    Extracts all coordinates from the boundary features and computes
    the axis-aligned bounding box. Returns None if no valid coordinates.
    """
    if not isinstance(geojson, dict):
        return None
    features = geojson.get("features", [])
    if not features:
        return None

    all_coords: List[Tuple[float, float]] = []
    for f in features:
        geom = f.get("geometry", {})
        _extract_coords(geom, all_coords)

    if not all_coords:
        return None

    lons = [c[0] for c in all_coords]
    lats = [c[1] for c in all_coords]
    bbox = BBox(west=min(lons), south=min(lats), east=max(lons), north=max(lats))
    if bbox.is_valid():
        return bbox
    return None


def _center_to_bbox(
    center: Tuple[float, float], buffer_km: float
) -> BBox:
    """Convert a center point + buffer distance to a BBox."""
    buffer_deg = buffer_km / 111.0
    return BBox(
        west=center[0] - buffer_deg,
        south=center[1] - buffer_deg,
        east=center[0] + buffer_deg,
        north=center[1] + buffer_deg,
    )


__all__ = [
    "_extract_coords",
    "_derive_bbox_from_boundary",
    "_center_to_bbox",
]