"""Deterministic conversion of a ParcelChangeSet into the PlannedState contract.

Replaces the old raw-GeoJSON _layout_configs_to_planned_state path for the
EXECUTE chain. Pure deterministic mapping: no LLM, no KG, no MIP.
"""

from __future__ import annotations

from typing import Any

from app.contracts.spatial.parcel_change_contracts import ParcelChange, ParcelChangeSet
from app.contracts.spatial.planned_state_contracts import (
    PlannedAxis,
    PlannedFacility,
    PlannedParcel,
    PlannedZoneOverlay,
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


def _target_by_id(intent: Any) -> dict[str, Any]:
    """Index typed targets so candidate roles survive materialization."""
    if intent is None:
        return {}
    result: dict[str, Any] = {}
    for field in (
        "site_area_targets",
        "project_targets",
        "zone_targets",
        "custom_zone_targets",
        "facilities",
        "road_targets",
        "development_axes",
        "linear_targets",
    ):
        items = (
            intent.get(field)
            if isinstance(intent, dict)
            else getattr(intent, field, None)
        )
        for item in items or []:
            target_id = str(
                (item.get("target_id") if isinstance(item, dict) else getattr(item, "target_id", ""))
                or (item.get("project_id") if isinstance(item, dict) else getattr(item, "project_id", ""))
                or (item.get("zone_id") if isinstance(item, dict) else getattr(item, "zone_id", ""))
                or ""
            )
            if target_id:
                result[target_id] = item
    return result


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
        project_ref=str(change.project_ref or ""),
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
        scenario_id=str(properties.get("scenario_id") or ""),
        candidate_id=str(properties.get("candidate_id") or ""),
        feature_id=str(properties.get("feature_id") or ""),
        lineage_id=str(properties.get("lineage_id") or properties.get("feature_id") or ""),
        relation_ids=[str(item) for item in properties.get("relation_ids") or []],
        source_refs=[str(item) for item in properties.get("source_refs") or []],
    )


def _axis_target_to_planned_axis(target: Any, geometry: str, target_id: str, properties: dict[str, Any]) -> PlannedAxis:
    return PlannedAxis(
        name=str(properties.get("name") or getattr(target, "label", "") or getattr(target, "reference_feature", "") or target_id),
        reference_feature=str(properties.get("reference_feature") or getattr(target, "reference_feature", "") or ""),
        direction=str(properties.get("direction") or getattr(target, "direction", "") or ""),
        geometry=geometry,
        derived_from_target=target_id,
        scenario_id=str(properties.get("scenario_id") or ""),
        candidate_id=str(properties.get("candidate_id") or ""),
        feature_id=str(properties.get("feature_id") or ""),
        lineage_id=str(properties.get("lineage_id") or properties.get("feature_id") or ""),
        relation_ids=[str(item) for item in properties.get("relation_ids") or []],
        source_refs=[str(item) for item in properties.get("source_refs") or []],
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
        scenario_id=str(properties.get("scenario_id") or ""),
        candidate_id=str(properties.get("candidate_id") or ""),
        feature_id=str(properties.get("feature_id") or ""),
        lineage_id=str(properties.get("lineage_id") or properties.get("feature_id") or ""),
        relation_ids=[str(item) for item in properties.get("relation_ids") or []],
        source_refs=[str(item) for item in properties.get("source_refs") or []],
        source_bsms=[str(item) for item in properties.get("source_bsms") or []],
        geometry_ref=str(properties.get("geometry_ref") or ""),
    )


def changeset_to_planned_state(
    changeset: ParcelChangeSet,
    intent: Any = None,
    layout_configs: list[dict[str, Any]] | None = None,
) -> PlannedState:
    """Build the authoritative PlannedState from changes and worker geometry."""
    parcels = [_change_to_planned_parcel(c) for c in changeset.changes]
    overlays: list[PlannedZoneOverlay] = []
    target_by_id = _target_by_id(intent)

    # Relation-aware execution can materialize a grounded candidate that is
    # not an existing BSM.  Preserve those immutable geometries in the
    # authoritative PlannedState as candidate-backed parcels so DELIVER and
    # final relation validation see the same target/candidate lineage.
    for feature in _layer_features(
        layout_configs or [], {"planned_project", "planned_zone"}
    ):
        properties = dict(feature.get("properties") or {})
        geometry = _geojson_to_wkt(feature.get("geometry"))
        target_id = str(properties.get("target_id") or properties.get("project_ref") or "")
        candidate_id = str(properties.get("candidate_id") or "")
        if not target_id or not candidate_id or not geometry:
            continue
        target = target_by_id.get(target_id)
        role = str(properties.get("materialization_role") or "")
        # Workers label direct candidate output as ``execution_geometry``;
        # that is a transport role, not the semantic overlay/footprint role.
        # Prefer the typed target role when the transport marker is present.
        if not role or role == "execution_geometry":
            role = str(getattr(target, "materialization_role", "") or role or "")
        feature_id = str(properties.get("feature_id") or candidate_id)
        scenario_id = str(properties.get("scenario_id") or "")
        source_refs = [
            str(ref)
            for ref in properties.get("source_refs") or []
            if str(ref).strip()
        ]
        if role in {
            "functional_overlay",
            "protection_overlay",
            "restoration_overlay",
        }:
            overlays.append(PlannedZoneOverlay(
                overlay_id=feature_id,
                materialization_role=role,
                name=str(properties.get("project_name") or target_id),
                geometry=geometry,
                target_ref=target_id,
                project_ref=target_id,
                candidate_id=candidate_id,
                scenario_id=scenario_id,
                feature_id=feature_id,
                lineage_id=feature_id,
                lineage_refs=source_refs,
                provenance_refs=source_refs,
            ))
            continue
        parcels.append(PlannedParcel(
            # A candidate is not a cadastral parcel and must never be looked
            # up as a BSM by legacy current-land-use consumers.
            bsm="",
            candidate_id=candidate_id,
            project_ref=target_id,
            planning_land_use=str(
                properties.get("project_category") or role or "planned"
            ),
            zone_type=role or "planned",
            geometry=geometry,
            target_ref=target_id,
            source_spec=str(
                properties.get("generation_operation")
                or "candidate_geometry_materialize"
            ),
            operation="create",
            decided_by="relation_aware_scenario",
            lineage_id=feature_id,
            feature_id=feature_id,
            scenario_id=scenario_id,
            materialization_role=role,
            source_refs=source_refs,
            claim_refs=list(properties.get("claim_refs") or []),
            source_instruction_id=str(
                properties.get("source_instruction_id") or target_id
            ),
            geometry_ref=str(properties.get("source_ref") or candidate_id),
        ))

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
        overlays=overlays,
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
