"""Render-layer derivation for the DELIVER stage.

Builds the ``render_result`` layer list from the EXECUTE outputs
(``layout_configs`` + ``planned_state``) so the GIS entry can push real
rendered layers to the frontend over SSE. Mirrors the layer contract used by
``app.api.render_routes``: each layer is ``{layerType, layerName, data}`` where
``data`` is a GeoJSON FeatureCollection. The same FeatureCollection is also
mirrored onto ``geojson`` so ``SSEPublisher``/``GISLayerConfig`` (which require
the ``geojson`` field) can consume the layers directly.

Layer precedence:
- ``layout_configs`` layers (real geometry produced by the EXECUTE workers)
  are collected verbatim and win.
- ``planned_state`` only supplements a ``function_zone`` layer when
  ``layout_configs`` does not already provide one.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

__all__ = ["build_render_layers"]


def _wkt_to_geojson(wkt: str) -> Optional[Dict[str, Any]]:
    """Parse a WKT string into a GeoJSON geometry dict; None on failure."""
    if not wkt:
        return None
    try:
        from shapely import wkt as shapely_wkt
        from shapely.geometry import mapping

        geom = shapely_wkt.loads(wkt)
        if geom is None or geom.is_empty:
            return None
        return mapping(geom)
    except Exception:
        return None


def _feature_collection(features: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {"type": "FeatureCollection", "features": features}


def _normalize_layer(config: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Normalize one layout_config entry to the {layerType, layerName, data} shape."""
    if not isinstance(config, dict):
        return None
    layer_type = config.get("layerType") or config.get("layer_type")
    if not layer_type:
        return None
    data = config.get("data") or config.get("geojson")
    if data is None and config.get("features") is not None:
        data = _feature_collection(config.get("features") or [])
    if not data or not data.get("features"):
        return None
    return {
        "layerType": layer_type,
        "layerName": config.get("layer_name") or config.get("layerName") or layer_type,
        "data": data,
        "geojson": data,
    }


def _function_zone_layer(planned_state: Any) -> Optional[Dict[str, Any]]:
    """Derive the function_zone layer from PlannedState parcels + zones."""
    features: List[Dict[str, Any]] = []
    for parcel in getattr(planned_state, "parcels", None) or []:
        geometry = _wkt_to_geojson(getattr(parcel, "geometry", "") or "")
        if geometry is None:
            continue
        features.append({
            "type": "Feature",
            "properties": {
                "bsm": getattr(parcel, "bsm", ""),
                "planning_land_use": getattr(parcel, "planning_land_use", ""),
                "zone_type": getattr(parcel, "zone_type", ""),
                "operation": getattr(parcel, "operation", ""),
                "area_ha": getattr(parcel, "area_ha", 0),
            },
            "geometry": geometry,
        })
    for zone in getattr(planned_state, "zones", None) or []:
        geometry = _wkt_to_geojson(getattr(zone, "geometry", "") or "")
        if geometry is None:
            continue
        features.append({
            "type": "Feature",
            "properties": {
                "zone_type": getattr(zone, "zone_type", ""),
                "name": getattr(zone, "name", ""),
                "area_ha": getattr(zone, "area_ha", 0),
            },
            "geometry": geometry,
        })
    if not features:
        return None
    data = _feature_collection(features)
    return {
        "layerType": "function_zone",
        "layerName": "功能分区",
        "data": data,
        "geojson": data,
    }


def build_render_layers(
    planned_state: Any,
    layout_configs: List[Dict[str, Any]],
    gis_data: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Derive the renderable layer list from PlannedState + layout_configs.

    Priority: collect ``layout_configs`` layers (real geometry from the
    EXECUTE workers) verbatim, then supplement a ``function_zone`` layer from
    ``planned_state`` when ``layout_configs`` does not already provide one.

    ``gis_data`` is accepted for signature compatibility with the DELIVER
    pipeline; baseline/constraint layers are not part of ``render_result`` and
    are not derived here.

    Empty inputs never raise; they yield ``[]``.
    """
    layers: List[Dict[str, Any]] = []
    present_types = set()

    for config in layout_configs or []:
        layer = _normalize_layer(config)
        if layer is None:
            continue
        present_types.add(layer["layerType"])
        layers.append(layer)

    if "function_zone" not in present_types:
        derived = _function_zone_layer(planned_state)
        if derived is not None:
            layers.append(derived)

    return layers
