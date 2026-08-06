"""Render Routes - derive renderable GeoJSON layers from planned artifacts.

GET /api/sessions/{session_id}/render-layers
- Reads the latest ``PlannedState`` artifact from ``FilesystemArtifactStore``.
- Optionally merges ``layout_configs`` from the live AgentState (best effort)
  for the richer execution layers (``planned_project`` etc.).
- Emits ``{layerType, layerName, data: FeatureCollection}`` entries.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException

from app.services.artifact_store import FilesystemArtifactStore

logger = logging.getLogger(__name__)
router = APIRouter()

_PLANNED_STATE_TYPE = "PlannedState"
_LAYER_TYPES = {"planned_project", "function_zone", "facility_point", "planned_road"}


def _wkt_to_geojson(wkt: str) -> Optional[Dict[str, Any]]:
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


def _function_zone_layer(state: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """function_zone from PlannedState parcels (reclassify) then zones."""
    features = []
    for parcel in state.get("parcels") or []:
        geometry = _wkt_to_geojson(parcel.get("geometry") or "")
        if geometry is None:
            continue
        features.append({
            "type": "Feature",
            "properties": {
                "bsm": parcel.get("bsm", ""),
                "planning_land_use": parcel.get("planning_land_use", ""),
                "zone_type": parcel.get("zone_type", ""),
                "operation": parcel.get("operation", ""),
                "area_ha": parcel.get("area_ha", 0),
            },
            "geometry": geometry,
        })
    for zone in state.get("zones") or []:
        geometry = _wkt_to_geojson(zone.get("geometry") or "")
        if geometry is None:
            continue
        features.append({
            "type": "Feature",
            "properties": {
                "zone_type": zone.get("zone_type", ""),
                "name": zone.get("name", ""),
                "area_ha": zone.get("area_ha", 0),
            },
            "geometry": geometry,
        })
    if not features:
        return None
    return {
        "layerType": "function_zone",
        "layerName": "功能分区",
        "data": _feature_collection(features),
    }


def _facility_point_layer(state: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """facility_point from PlannedState facilities (lon/lat -> Point)."""
    features = []
    for facility in state.get("facilities") or []:
        lon = facility.get("lon") or 0.0
        lat = facility.get("lat") or 0.0
        if not lon and not lat:
            continue
        features.append({
            "type": "Feature",
            "properties": {
                "name": facility.get("name", ""),
                "facility_type": facility.get("facility_type", ""),
                "service_radius": facility.get("service_radius", 0),
            },
            "geometry": {"type": "Point", "coordinates": [float(lon), float(lat)]},
        })
    if not features:
        return None
    return {
        "layerType": "facility_point",
        "layerName": "公共服务设施",
        "data": _feature_collection(features),
    }


def _planned_road_layer(state: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """planned_road from PlannedState roads (metadata only, no geometry stored)."""
    features = []
    for road in state.get("roads") or []:
        features.append({
            "type": "Feature",
            "properties": {
                "name": road.get("name", ""),
                "road_level": road.get("road_level", ""),
                "width_m": road.get("width_m", 0),
            },
            "geometry": None,
        })
    if not features:
        return None
    return {
        "layerType": "planned_road",
        "layerName": "规划道路",
        "data": _feature_collection(features),
    }


def _derive_layers(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    layers = []
    for builder in (_function_zone_layer, _facility_point_layer, _planned_road_layer):
        layer = builder(state)
        if layer:
            layers.append(layer)
    return layers


def _normalize_layout_layer(config: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Adapt a raw layout_config entry to the {layerType, layerName, data} shape."""
    layer_type = config.get("layerType") or config.get("layer_type")
    if layer_type not in _LAYER_TYPES:
        return None
    data = config.get("data")
    if data is None and config.get("features") is not None:
        data = _feature_collection(config.get("features") or [])
    if not data or not data.get("features"):
        return None
    return {
        "layerType": layer_type,
        "layerName": config.get("layer_name") or config.get("layerName") or layer_type,
        "data": data,
    }


def _normalize_layout_layers(configs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    layers = []
    for config in configs or []:
        if not isinstance(config, dict):
            continue
        layer = _normalize_layout_layer(config)
        if layer:
            layers.append(layer)
    return layers


async def _get_layout_configs(session_id: str) -> List[Dict[str, Any]]:
    """Best-effort read of live ``layout_configs`` from the AgentState."""
    try:
        from app.services.runtime import PlanningRuntimeService

        state = await PlanningRuntimeService.aget_state_values(session_id)
        return list((state or {}).get("layout_configs") or [])
    except Exception:
        return []


@router.get("/api/sessions/{session_id}/render-layers")
async def get_render_layers(session_id: str):
    """Derive renderable GeoJSON layers from the latest PlannedState artifact.

    ``layout_configs`` layers (when available) take precedence over the
    PlannedState-derived fallbacks; missing layer types are simply omitted.
    """
    store = FilesystemArtifactStore()
    refs = [
        ref for ref in store.list_by_run(session_id)
        if ref.artifact_type == _PLANNED_STATE_TYPE
    ]
    if not refs:
        raise HTTPException(
            status_code=404,
            detail=f"PlannedState artifact not found for session: {session_id}",
        )
    planned_state = store.retrieve(refs[0])

    layers_by_type: Dict[str, Dict[str, Any]] = {}
    for layer in _normalize_layout_layers(await _get_layout_configs(session_id)):
        layers_by_type[layer["layerType"]] = layer
    for layer in _derive_layers(planned_state):
        layers_by_type.setdefault(layer["layerType"], layer)

    return {
        "session_id": session_id,
        "layers": [layers_by_type[key] for key in sorted(layers_by_type)],
    }


__all__ = ["router"]
