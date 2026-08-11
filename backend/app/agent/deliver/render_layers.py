"""Derive every DELIVER render layer from the authoritative PlannedState."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

__all__ = [
    "build_render_layers",
    "build_delivery_render_layers",
    "build_complete_planned_geojson",
]


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


def _parcel_value(parcel: Any, key: str, default: Any = None) -> Any:
    if isinstance(parcel, dict):
        return parcel.get(key, default)
    return getattr(parcel, key, default)


def _feature_bsm(feature: Dict[str, Any]) -> str:
    properties = feature.get("properties") or {}
    return str(properties.get("BSM") or properties.get("bsm") or "")


def _planned_parcel_feature(parcel: Any) -> Optional[Dict[str, Any]]:
    geometry = _wkt_to_geojson(_parcel_value(parcel, "geometry", "") or "")
    bsm = str(_parcel_value(parcel, "bsm", "") or "")
    if geometry is None or not bsm:
        return None
    return {
        "type": "Feature",
        "properties": {
            "BSM": bsm,
            "planning_land_use": _parcel_value(parcel, "planning_land_use", ""),
            "zone_type": _parcel_value(parcel, "zone_type", ""),
            "area_ha": _parcel_value(parcel, "area_ha", 0),
            "operation": _parcel_value(parcel, "operation", ""),
            "derived_from_bsms": list(
                _parcel_value(parcel, "derived_from_bsms", None) or []
            ),
        },
        "geometry": geometry,
    }


def _tag_planned_feature(
    feature: Dict[str, Any],
    *,
    preserved: bool,
    provenance: str,
) -> Dict[str, Any]:
    result = dict(feature)
    properties = dict(result.get("properties") or {})
    if preserved:
        properties.setdefault("change_status", "preserved")
        properties.setdefault("planning_status", "unchanged_preserved")
    else:
        properties.setdefault("change_status", "planned")
        properties.setdefault("planning_status", "planned")
    properties.setdefault("provenance", provenance)
    properties.setdefault("planning_provenance", provenance)
    result["properties"] = properties
    return result


def build_complete_planned_geojson(
    allocated_geojson: Optional[Dict[str, Any]],
    current_geojson: Optional[Dict[str, Any]],
    planned_state: Any = None,
) -> Dict[str, Any]:
    """Build one auditable, complete planned land-use snapshot.

    ``allocated_geojson`` may contain only changed parcels. The current layer
    is therefore the authoritative base: every current parcel absent from the
    planned changes is carried through as an unchanged parcel. PlannedState
    parcels are allowed to replace a current parcel only when their BSM (or a
    source BSM) is auditable against that same current snapshot.
    """
    import copy

    current_features = list((current_geojson or {}).get("features", []) or [])
    allocated_features = list((allocated_geojson or {}).get("features", []) or [])
    current_by_bsm = {
        _feature_bsm(feature): feature
        for feature in current_features
        if _feature_bsm(feature)
    }
    current_bsms = set(current_by_bsm)

    planned_by_bsm: Dict[str, Dict[str, Any]] = {}
    planned_parcels = _parcel_value(planned_state, "parcels", None) or []
    for parcel in planned_parcels:
        bsm = str(_parcel_value(parcel, "bsm", "") or "")
        sources = {
            str(source)
            for source in (_parcel_value(parcel, "derived_from_bsms", None) or [])
            if source
        }
        if bsm not in current_bsms and not sources.intersection(current_bsms):
            continue
        feature = _planned_parcel_feature(parcel)
        if feature is not None:
            keys = [bsm] if bsm in current_bsms else sorted(sources.intersection(current_bsms))
            for key in keys:
                planned_by_bsm[key] = feature

    allocated_by_bsm: Dict[str, Dict[str, Any]] = {}
    allocated_without_bsm: List[Dict[str, Any]] = []
    for feature in allocated_features:
        bsm = _feature_bsm(feature)
        properties = feature.get("properties") or {}
        sources = {
            str(source)
            for source in (
                properties.get("derived_from_bsms")
                or properties.get("source_bsms")
                or []
            )
            if source
        }
        if current_bsms and bsm not in current_bsms and not sources.intersection(current_bsms):
            continue
        if bsm:
            keys = [bsm] if bsm in current_bsms else sorted(sources.intersection(current_bsms))
            for key in keys or [bsm]:
                allocated_by_bsm[key] = feature
        elif not current_bsms:
            allocated_without_bsm.append(feature)

    def merge_planned(
        feature: Dict[str, Any],
        planned_feature: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        result = copy.deepcopy(feature)
        if planned_feature is None:
            props = result.get("properties") or {}
            changed = any(
                props.get(key) not in (None, "", [], {})
                for key in (
                    "planning_land_use",
                    "assigned_zone",
                    "operation",
                    "planning_status",
                    "change_status",
                )
            )
            return _tag_planned_feature(
                result,
                preserved=not changed,
                provenance=(
                    "allocated_planned_landuse"
                    if changed
                    else "current_landuse_delivery_snapshot"
                ),
            )
        planned_props = planned_feature.get("properties") or {}
        props = dict(result.get("properties") or {})
        for key in (
            "planning_land_use",
            "zone_type",
            "area_ha",
            "operation",
            "derived_from_bsms",
        ):
            value = planned_props.get(key)
            if value not in (None, "", [], {}):
                props[key] = value
        result["properties"] = props
        if planned_feature.get("geometry") is not None:
            result["geometry"] = planned_feature["geometry"]
        preserved = str(props.get("operation") or "") == "preserve"
        return _tag_planned_feature(
            result,
            preserved=preserved,
            provenance="planned_state_snapshot",
        )

    complete: List[Dict[str, Any]] = []
    for current in current_features:
        bsm = _feature_bsm(current)
        feature = allocated_by_bsm.pop(bsm, None) if bsm else None
        feature = feature or current
        complete.append(merge_planned(feature, planned_by_bsm.pop(bsm, None)))

    for bsm, feature in allocated_by_bsm.items():
        complete.append(merge_planned(feature, planned_by_bsm.pop(bsm, None)))
    for feature in allocated_without_bsm:
        complete.append(merge_planned(feature, None))

    return _feature_collection(complete)


def _delivery_gis_data(gis_data: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Normalize known bundle/control-layer aliases for delivery rendering."""
    current = dict(gis_data or {})
    aliases = {
        "ecological_protection_geojson": ("ecological_redline_geojson",),
        "construction_boundary_geojson": ("construction_zone_geojson",),
    }
    for target, candidates in aliases.items():
        if current.get(target):
            continue
        for candidate in candidates:
            if current.get(candidate):
                current[target] = current[candidate]
                break
    return current


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


def build_delivery_render_layers(
    planned_state: Any,
    allocated_geojson: Optional[Dict[str, Any]],
    gis_data: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Build the complete delivery view from one current/planned snapshot.

    The planned parcel layer is materialized at delivery time. If execution
    produced no parcel changes, the current layer is copied as preserved
    output; it is never synthesized from the sparse PlannedState.
    """
    from app.modules.spatial_ops.output.map_layers import build_map_layers

    current = _delivery_gis_data(gis_data)
    planned = build_complete_planned_geojson(
        allocated_geojson,
        current.get("landuse_current_geojson"),
        planned_state,
    )
    if planned.get("features"):
        layouts = build_render_layers(planned_state)
        layouts.insert(0, {
            "layerType": "complete_planned_landuse",
            "layerName": "完整期末地类（含未修改地块）",
            "data": planned,
            "geojson": planned,
            "color": "#2563eb",
        })
        return build_map_layers(layouts, current)
    return build_map_layers(build_render_layers(planned_state), current)
