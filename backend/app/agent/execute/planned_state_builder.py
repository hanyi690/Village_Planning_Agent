"""Deterministic conversion of a ParcelChangeSet into the PlannedState contract.

Replaces the old raw-GeoJSON _layout_configs_to_planned_state path for the
EXECUTE chain. Pure deterministic mapping: no LLM, no KG, no MIP.
"""

from __future__ import annotations

from typing import Any

from app.modules.schema.contracts.parcel_change_contracts import ParcelChange, ParcelChangeSet
from app.modules.schema.contracts.planned_state_contracts import (
    PlannedAxis,
    PlannedFacility,
    PlannedParcel,
    PlannedRoad,
    PlannedState,
)


def _geometry_area_ha(wkt: str) -> float:
    """Area in hectares from a WKT geometry; 0.0 on empty input or parse failure."""
    if not wkt:
        return 0.0
    try:
        from shapely import wkt as shapely_wkt

        geom = shapely_wkt.loads(wkt)
        if geom is None or geom.is_empty:
            return 0.0
        return float(geom.area) / 10000
    except Exception:
        return 0.0


def _geojson_to_wkt(geometry: Any) -> str:
    """Convert one GeoJSON geometry to WKT without inventing geometry."""
    if not isinstance(geometry, dict) or not geometry.get("type"):
        return ""
    try:
        from shapely.geometry import shape

        value = shape(geometry)
        if value.is_empty:
            return ""
        return value.wkt
    except Exception:
        return ""


def _target_map(intent: Any, field: str) -> dict[str, Any]:
    return {
        str(getattr(target, "target_id", "")): target
        for target in (getattr(intent, field, None) or [])
        if str(getattr(target, "target_id", ""))
    } if intent is not None else {}


def _layer_features(layout_configs: list[dict[str, Any]], layer_types: set[str]):
    for layer in layout_configs or []:
        if not isinstance(layer, dict):
            continue
        layer_type = str(layer.get("layerType") or layer.get("layer_type") or "")
        if layer_type not in layer_types:
            continue
        data = layer.get("data") or layer.get("geojson") or layer
        for feature in data.get("features") or []:
            if isinstance(feature, dict):
                yield feature


def _feature_target_ids(properties: dict[str, Any]) -> list[str]:
    values = properties.get("target_ids") or []
    if not isinstance(values, list):
        values = [values]
    target_id = properties.get("target_id")
    if target_id:
        values.insert(0, target_id)
    return list(dict.fromkeys(str(value) for value in values if str(value)))


def _change_to_planned_parcel(change: ParcelChange) -> PlannedParcel:
    after = change.after_classification
    before = change.before_classification
    code = after.code if after else (before.code if before else "")
    return PlannedParcel(
        bsm=change.bsm,
        planning_land_use=code,
        zone_type=code,
        area_ha=change.new_area_ha,
        geometry=change.after_geometry_wkt,
        derived_from_bsms=list(change.derived_from_bsms),
        operation=change.action,
        decided_by="rule",
        area_change_ha=change.new_area_ha - _geometry_area_ha(change.before_geometry_wkt),
    )


def _road_target_to_planned_road(target: Any, geometry: str, target_id: str, properties: dict[str, Any]) -> PlannedRoad:
    return PlannedRoad(
        name=str(properties.get("name") or getattr(target, "road_level", "") or target_id),
        road_level=str(properties.get("road_level") or getattr(target, "road_level", "") or ""),
        width_m=float(properties.get("width_m") or getattr(target, "width_m", 0.0) or 0.0),
        geometry=geometry,
        derived_from_target=target_id,
    )


def _axis_target_to_planned_axis(target: Any, geometry: str, target_id: str, properties: dict[str, Any]) -> PlannedAxis:
    return PlannedAxis(
        name=str(properties.get("name") or getattr(target, "label", "") or getattr(target, "reference_feature", "") or target_id),
        reference_feature=str(properties.get("reference_feature") or getattr(target, "reference_feature", "") or ""),
        direction=str(properties.get("direction") or getattr(target, "direction", "") or ""),
        geometry=geometry,
        derived_from_target=target_id,
    )


def _facility_target_to_planned_facility(target: Any, geometry: str, target_id: str, properties: dict[str, Any]) -> PlannedFacility:
    anchor = getattr(target, "anchor_point", None) or (0.0, 0.0)
    try:
        from shapely import wkt as shapely_wkt

        point = shapely_wkt.loads(geometry)
        if point.geom_type == "Point":
            anchor = (point.x, point.y)
    except Exception:
        pass
    return PlannedFacility(
        name=str(properties.get("name") or properties.get("facility_type") or getattr(target, "type", "") or target_id),
        facility_type=str(properties.get("facility_type") or getattr(target, "type", "") or ""),
        lon=float(anchor[0]),
        lat=float(anchor[1]),
        service_radius=float(properties.get("service_radius") or getattr(target, "service_radius", 0.0) or 0.0),
        geometry=geometry,
        derived_from_target=target_id,
    )


def changeset_to_planned_state(
    changeset: ParcelChangeSet,
    intent: Any = None,
    layout_configs: list[dict[str, Any]] | None = None,
) -> PlannedState:
    """Build the authoritative PlannedState from changes and worker geometry."""
    parcels = [_change_to_planned_parcel(c) for c in changeset.changes]

    roads: list[PlannedRoad] = []
    axes: list[PlannedAxis] = []
    facilities: list[PlannedFacility] = []
    facility_targets = _target_map(intent, "facilities")
    road_targets = _target_map(intent, "road_targets")
    axis_targets = _target_map(intent, "development_axes")

    for feature in _layer_features(layout_configs or [], {"facility_point"}):
        properties = dict(feature.get("properties") or {})
        geometry = _geojson_to_wkt(feature.get("geometry"))
        if not geometry:
            continue
        target_ids = _feature_target_ids(properties)
        if not target_ids and len(facility_targets) == 1:
            target_ids = list(facility_targets)
        for target_id in target_ids:
            facilities.append(_facility_target_to_planned_facility(
                facility_targets.get(target_id), geometry, target_id, properties
            ))

    for feature in _layer_features(
        layout_configs or [], {"planned_road", "planned_road_candidates"}
    ):
        properties = dict(feature.get("properties") or {})
        geometry = _geojson_to_wkt(feature.get("geometry"))
        if not geometry:
            continue
        target_ids = _feature_target_ids(properties)
        if not target_ids and len(road_targets) == 1:
            target_ids = list(road_targets)
        for target_id in target_ids:
            roads.append(_road_target_to_planned_road(
                road_targets.get(target_id), geometry, target_id, properties
            ))

    for feature in _layer_features(layout_configs or [], {"infrastructure", "development_axis"}):
        properties = dict(feature.get("properties") or {})
        geometry = _geojson_to_wkt(feature.get("geometry"))
        if not geometry:
            continue
        target_ids = _feature_target_ids(properties)
        if not target_ids and len(axis_targets) == 1:
            target_ids = list(axis_targets)
        for target_id in target_ids:
            axes.append(_axis_target_to_planned_axis(
                axis_targets.get(target_id), geometry, target_id, properties
            ))

    # zones stays empty: zone parcel changes arrive as reclassify ParcelChanges,
    # which map to PlannedParcel, not PlannedZone.
    return PlannedState(
        version="v1",
        parcels=parcels,
        zones=[],
        facilities=facilities,
        roads=roads,
        axes=axes,
        source="parcel_change_set+worker_geometry",
        provenance=changeset.provenance,
    )


__all__ = [
    "changeset_to_planned_state",
    "_change_to_planned_parcel",
]
