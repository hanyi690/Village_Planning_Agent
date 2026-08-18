"""Build DELIVER render layers from the authoritative spatial snapshot."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

__all__ = [
    "build_planned_overlay_layers",
    "build_delivery_render_layers",
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
        role = str(getattr(parcel, "materialization_role", "") or "")
        if role and role != "land_use_assignment":
            continue
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
        "color": "#f59e0b",
        "style": {"fill-opacity": 0.10, "line-opacity": 0.75},
    }


def _project_layer(planned_state: Any) -> Optional[Dict[str, Any]]:
    """Expose project-bound parcel footprints produced by EXECUTE."""
    features: List[Dict[str, Any]] = []
    for parcel in getattr(planned_state, "parcels", None) or []:
        project_ref = str(getattr(parcel, "project_ref", "") or "")
        role = str(getattr(parcel, "materialization_role", "") or "")
        if role and role not in {"site_footprint", "project_footprint"}:
            continue
        geometry = _wkt_to_geojson(getattr(parcel, "geometry", "") or "")
        if not project_ref or geometry is None:
            continue
        features.append({
            "type": "Feature",
            "properties": {
                "project_ref": project_ref,
                "bsm": getattr(parcel, "bsm", ""),
                "planning_land_use": getattr(parcel, "planning_land_use", ""),
                "operation": getattr(parcel, "operation", ""),
            },
            "geometry": geometry,
        })
    return _layer("planned_project", "规划项目落地", features)


def _semantic_overlay_layers(planned_state: Any) -> List[Dict[str, Any]]:
    """Expose non-exclusive candidate overlays without parcel semantics."""
    by_type: dict[str, list[dict[str, Any]]] = {}
    names = {
        "functional_overlay": ("planning_zone", "规划功能叠加"),
        "protection_overlay": ("protection_zone", "生态保护范围"),
        "restoration_overlay": ("restoration_zone", "生态修复范围"),
    }
    for overlay in getattr(planned_state, "overlays", None) or []:
        role = str(getattr(overlay, "materialization_role", "") or "")
        layer_type, layer_name = names.get(role, ("planning_zone", "规划叠加"))
        geometry = _wkt_to_geojson(getattr(overlay, "geometry", "") or "")
        if geometry is None:
            continue
        by_type.setdefault(layer_type, []).append({
            "type": "Feature",
            "properties": {
                "target_id": getattr(overlay, "target_ref", ""),
                "project_ref": getattr(overlay, "project_ref", ""),
                "candidate_id": getattr(overlay, "candidate_id", ""),
                "feature_id": getattr(overlay, "feature_id", ""),
                "materialization_role": role,
            },
            "geometry": geometry,
        })
    layer_names = {
        "planning_zone": "规划功能叠加",
        "protection_zone": "生态保护范围",
        "restoration_zone": "生态修复范围",
    }
    return [
        _layer(layer_type, layer_names.get(layer_type, "规划叠加"), features)
        for layer_type, features in sorted(by_type.items())
        if features
    ]


def _project_point_layer(planned_state: Any) -> Optional[Dict[str, Any]]:
    """Expose a small centroid marker for every landed project footprint."""
    features: List[Dict[str, Any]] = []
    for project in getattr(planned_state, "project_points", None) or []:
        geometry = _wkt_to_geojson(getattr(project, "geometry", "") or "")
        if geometry is None:
            continue
        features.append({
            "type": "Feature",
            "properties": {
                "project_ref": getattr(project, "project_ref", ""),
                "project_name": getattr(project, "name", ""),
                "marker_size": "small",
            },
            "geometry": geometry,
        })
    for parcel in getattr(planned_state, "parcels", None) or []:
        project_ref = str(getattr(parcel, "project_ref", "") or "")
        geometry = _wkt_to_geojson(getattr(parcel, "geometry", "") or "")
        if not project_ref or geometry is None:
            continue
        try:
            from shapely.geometry import shape, mapping

            point = mapping(shape(geometry).representative_point())
        except Exception:
            continue
        features.append({
            "type": "Feature",
            "properties": {
                "project_ref": project_ref,
                "bsm": getattr(parcel, "bsm", ""),
                "marker_size": "small",
            },
            "geometry": point,
        })
    return _layer("planned_project_point", "规划项目定位点", features)


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
                "candidate_id": getattr(facility, "candidate_id", ""),
                "feature_id": getattr(facility, "feature_id", ""),
                "lineage_id": getattr(facility, "lineage_id", ""),
                "scenario_id": getattr(facility, "scenario_id", ""),
                "source_refs": list(getattr(facility, "source_refs", None) or []),
                "source_bsms": list(getattr(facility, "source_bsms", None) or []),
                "geometry_ref": getattr(facility, "geometry_ref", ""),
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
                "action": getattr(road, "action", ""),
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


def _planned_changes_layer(planned: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Expose changed parcels separately from the complete planned base layer."""
    changed = [
        feature
        for feature in planned.get("features", [])
        if (feature.get("properties") or {}).get("change_status")
        not in {None, "preserved", "unchanged"}
    ]
    if not changed:
        return None
    return _layer("planned_changes", "EXECUTE 实际变更", changed) | {
        "color": "#ef4444",
        "force_layer_colors": True,
        "style": {"fill-opacity": 0.78, "line-color": "#b91c1c", "line-width": 2},
    }


def build_planned_overlay_layers(
    planned_state: Any,
) -> List[Dict[str, Any]]:
    """Materialize planned overlay payloads at the snapshot-build boundary.

    This is not a renderer input.  The resulting GeoJSON is written into the
    DeliverySpatialSnapshot before any renderer/exporter is called.
    """
    layers: List[Dict[str, Any]] = []
    for builder in (
        _function_zone_layer,
        _project_layer,
        _semantic_overlay_layers,
        _project_point_layer,
        _facility_layer,
        _road_layer,
        _axis_layer,
    ):
        layer = builder(planned_state)
        if isinstance(layer, list):
            layers.extend(item for item in layer if item is not None)
        elif layer is not None:
            layers.append(layer)

    return layers


def build_delivery_render_layers(
    snapshot: Any,
) -> List[Dict[str, Any]]:
    """Build all frontend layers by reading one DeliverySpatialSnapshot."""
    from app.infrastructure.rendering.map_layers import build_map_layers
    from app.spatial.delivery import colorize_feature_collection

    from app.infrastructure.export.delivery_snapshot import (
        load_complete_planned_geojson,
        load_snapshot_gis_data,
        load_snapshot_planned_overlays,
    )

    current = _delivery_gis_data(load_snapshot_gis_data(snapshot))
    if current.get("landuse_current_geojson"):
        current["landuse_current_geojson"] = colorize_feature_collection(
            current["landuse_current_geojson"]
        )
    planned = colorize_feature_collection(load_complete_planned_geojson(snapshot))
    layouts: list[dict[str, Any]] = []
    if planned.get("features"):
        layouts.append({
            "layerType": "complete_planned_landuse",
            "layerName": "完整期末地类（含未修改地块）",
            "data": planned,
            "geojson": planned,
            "color": "#2563eb",
            "default_visible": True,
            "style": {
                "fill-opacity": 0.18,
                "line-opacity": 0.85,
                "line-color": "#475569",
                "line-width": 1,
            },
        })
    overlay_names = {
        "planned_project_geojson": ("planned_project", "规划项目落地", "#f97316"),
        "planned_project_point_geojson": ("planned_project_point", "规划项目定位点", "#b91c1c"),
        "planned_facility_geojson": ("facility_point", "公共服务设施", "#2563eb"),
        "planned_road_geojson": ("planned_road", "规划道路", "#d97706"),
        "planned_axis_geojson": ("development_axis", "发展轴", "#7c3aed"),
        "planned_zone_geojson": ("planning_zone", "规划分区", "#16a34a"),
        "planned_restoration_geojson": ("restoration_zone", "生态修复", "#15803d"),
        "planned_protection_geojson": ("protection_zone", "保护范围", "#7c3aed"),
    }
    for key, payload in load_snapshot_planned_overlays(snapshot).items():
        if not (payload.get("features") or []):
            continue
        layer_type, layer_name, color = overlay_names.get(
            key, (key.removesuffix("_geojson"), key, "#64748b")
        )
        layouts.append({
            "layerType": layer_type,
            "layerName": layer_name,
            "data": payload,
            "geojson": payload,
            "color": color,
            "default_visible": layer_type in {
                "planned_project",
                "planned_project_point",
                "facility_point",
                "planned_road",
                "development_axis",
                "planning_zone",
                "restoration_zone",
                "protection_zone",
            },
            "force_layer_colors": layer_type in {
                "planned_project",
                "planned_project_point",
                "facility_point",
                "planned_road",
                "development_axis",
            },
            "style": {
                "fill-opacity": 0.45,
                "line-opacity": 0.9,
                "line-width": 7 if layer_type == "planned_road" else 2,
            },
        })
    changes_layer = _planned_changes_layer(planned)
    result = build_map_layers(layouts, current)
    if changes_layer is not None:
        changes_layer["default_visible"] = True
        result.extend(build_map_layers([changes_layer], {}))
    return result
