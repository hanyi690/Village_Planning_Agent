"""Derive every DELIVER render layer from the authoritative PlannedState."""

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


def _facility_layer(planned_state: Any) -> Optional[Dict[str, Any]]:
    features: List[Dict[str, Any]] = []
    for facility in getattr(planned_state, "facilities", None) or []:
        geometry = _wkt_to_geojson(getattr(facility, "geometry", "") or "")
        if geometry is None:
            lon = float(getattr(facility, "lon", 0.0) or 0.0)
            lat = float(getattr(facility, "lat", 0.0) or 0.0)
            if not lon and not lat:
                continue
            geometry = {"type": "Point", "coordinates": [lon, lat]}
        features.append({
            "type": "Feature",
            "properties": {
                "target_id": getattr(facility, "derived_from_target", ""),
                "name": getattr(facility, "name", ""),
                "facility_type": getattr(facility, "facility_type", ""),
                "service_radius": getattr(facility, "service_radius", 0),
            },
            "geometry": geometry,
        })
    return _layer("facility_point", "公共服务设施", features)


def _road_layer(planned_state: Any) -> Optional[Dict[str, Any]]:
    features: List[Dict[str, Any]] = []
    for road in getattr(planned_state, "roads", None) or []:
        geometry = _wkt_to_geojson(getattr(road, "geometry", "") or "")
        if geometry is None:
            continue
        features.append({
            "type": "Feature",
            "properties": {
                "target_id": getattr(road, "derived_from_target", ""),
                "name": getattr(road, "name", ""),
                "road_level": getattr(road, "road_level", ""),
                "width_m": getattr(road, "width_m", 0),
            },
            "geometry": geometry,
        })
    return _layer("planned_road", "规划道路", features)


def _axis_layer(planned_state: Any) -> Optional[Dict[str, Any]]:
    features: List[Dict[str, Any]] = []
    for axis in getattr(planned_state, "axes", None) or []:
        geometry = _wkt_to_geojson(getattr(axis, "geometry", "") or "")
        if geometry is None:
            continue
        features.append({
            "type": "Feature",
            "properties": {
                "target_id": getattr(axis, "derived_from_target", ""),
                "name": getattr(axis, "name", ""),
                "reference_feature": getattr(axis, "reference_feature", ""),
                "direction": getattr(axis, "direction", ""),
            },
            "geometry": geometry,
        })
    return _layer("development_axis", "发展轴", features)


def _layer(
    layer_type: str,
    layer_name: str,
    features: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    if not features:
        return None
    data = _feature_collection(features)
    return {
        "layerType": layer_type,
        "layerName": layer_name,
        "data": data,
        "geojson": data,
    }


def build_render_layers(
    planned_state: Any,
) -> List[Dict[str, Any]]:
    """Derive renderable layers only from PlannedState; empty state is mapless."""
    layers: List[Dict[str, Any]] = []
    for builder in (
        _function_zone_layer,
        _facility_layer,
        _road_layer,
        _axis_layer,
    ):
        layer = builder(planned_state)
        if layer is not None:
            layers.append(layer)

    return layers
