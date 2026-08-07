"""File-name and layer-type inference for the data catalog.

Defensive fallback for rows persisted with a placeholder/empty ``gis_data_type``
(``upload`` / ``auto`` / ``unknown`` / ``None``) — e.g. uploads stored before
type normalization existed. Without this, those features would be silently
dropped at bundle build.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

_DIRTY_LAYER_TYPES = {"upload", "auto", "unknown", ""}


def _infer_layer_key_from_upload(item: Dict[str, Any]) -> Optional[str]:
    """Re-infer a GIS layer key from filename + GeoJSON properties.

    Defensive fallback for rows persisted with a placeholder/empty
    ``gis_data_type`` (``upload`` / ``auto`` / ``unknown`` / ``None``) —
    e.g. uploads stored before type normalization existed. Without this,
    those features would be silently dropped at bundle build (the KG
    prebuild then produces an empty graph).
    """
    filename = str(
        item.get("original_filename") or item.get("filename") or ""
    ).lower()
    # The administrative boundary *line* is a distinct layer.  Check it
    # before the broader boundary match; otherwise a file named
    # ``admin_boundary_line.geojson`` is routed to ``admin_area`` and every
    # line feature is rejected by the polygon model.
    if "admin_boundary_line" in filename or "行政界线" in filename:
        return "admin_boundary_line"
    if "boundary" in filename or "边界" in filename:
        return "boundary"
    if "landuse" in filename or "用地" in filename or "现状" in filename:
        return "landuse_current"
    if "road" in filename or "道路" in filename:
        return "road"
    if "annotation" in filename or "注记" in filename:
        return "current_annotation"
    if "water" in filename or "水" in filename or "河流" in filename:
        return "water"
    if "residential" in filename or "住宅" in filename or "居民" in filename:
        return "residential"
    if "construction_zone" in filename or "建设区" in filename:
        return "construction_zone"
    if "farmland_protection" in filename or "基本农田" in filename:
        return "farmland_protection"
    if "ecological_protection" in filename or "生态保护" in filename:
        return "ecological_protection"
    if "historical_protection" in filename or "历史保护" in filename:
        return "historical_protection"
    if "geological_hazard" in filename or "地质灾害" in filename:
        return "geological_hazard_points"

    geojson = item.get("gis_data") or {}
    features = geojson.get("features") or []
    if features:
        props = features[0].get("properties") or {}
        name = str(props.get("name", "") or "").lower()
        layer = str(props.get("layer", "") or "").lower()
        if "边界" in name or "boundary" in layer:
            return "boundary"
        if "道路" in name or "road" in layer:
            return "road"
        if "用地" in name or "landuse" in layer:
            return "landuse_current"
        if "注记" in name or "annotation" in layer:
            return "current_annotation"
        if "水" in name or "water" in layer or "河流" in name:
            return "water"
        if "住宅" in name or "residential" in layer:
            return "residential"
    return None


__all__ = [
    "_DIRTY_LAYER_TYPES",
    "_infer_layer_key_from_upload",
]