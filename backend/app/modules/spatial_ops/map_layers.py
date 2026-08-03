"""Pure conversion from backend GIS layers to the frontend map contract."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.utils.sse_events import GISLayerConfig


def build_map_layers(
    layout_configs: Optional[List[Dict[str, Any]]],
    gis_data: Dict[str, Optional[Dict[str, Any]]],
) -> List[Dict[str, Any]]:
    """Build frontend MapLibre layers without Agent or LangChain dependencies."""
    layers: List[Dict[str, Any]] = []

    if gis_data.get("landuse_current_geojson"):
        layers.append({
            "geojson": gis_data["landuse_current_geojson"],
            "layer_type": "function_zone",
            "layer_name": "current_landuse",
            "color": "#d1d5db",
        })

    for config in layout_configs or []:
        if not isinstance(config, dict):
            continue
        geojson = config.get("data") or config.get("geojson")
        if geojson is None and config.get("features") is not None:
            geojson = {
                "type": "FeatureCollection",
                "features": config.get("features") or [],
            }
        if not geojson:
            continue
        layer_type = (
            config.get("layerType")
            or config.get("layer_type")
            or "function_zone"
        )
        layers.append({
            "geojson": geojson,
            "layer_type": layer_type,
            "layer_name": config.get("layer_name") or layer_type,
            "color": config.get("color"),
            "style": config.get("style"),
        })

    if gis_data.get("boundary_geojson"):
        layers.append({
            "geojson": gis_data["boundary_geojson"],
            "layer_type": "boundary",
            "layer_name": "boundary",
            "color": "#3388ff",
        })

    return [GISLayerConfig(**layer).model_dump(by_alias=True) for layer in layers]


__all__ = ["build_map_layers"]
