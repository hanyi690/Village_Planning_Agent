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


def _road_target_to_planned_road(target: Any) -> PlannedRoad:
    return PlannedRoad(
        name=target.road_level or "",
        road_level=target.road_level or "",
        width_m=float(target.width_m or 0.0),
        derived_from_target="",
    )


def _axis_target_to_planned_axis(target: Any) -> PlannedAxis:
    return PlannedAxis(
        name=target.label or target.reference_feature or "",
        reference_feature=target.reference_feature or "",
        direction=target.direction or "",
        derived_from_target="",
    )


def _facility_target_to_planned_facility(target: Any) -> PlannedFacility:
    anchor = target.anchor_point or (0.0, 0.0)
    return PlannedFacility(
        name=target.type or "",
        facility_type=target.type or "",
        lon=float(anchor[0]),
        lat=float(anchor[1]),
        service_radius=float(target.service_radius or 0.0),
        derived_from_target="",
    )


def changeset_to_planned_state(changeset: ParcelChangeSet, intent: Any = None) -> PlannedState:
    """Build a PlannedState from a ParcelChangeSet, optionally enriching intent layers."""
    parcels = [_change_to_planned_parcel(c) for c in changeset.changes]

    roads: list[PlannedRoad] = []
    axes: list[PlannedAxis] = []
    facilities: list[PlannedFacility] = []
    if intent is not None:
        roads = [_road_target_to_planned_road(t) for t in (getattr(intent, "road_targets", None) or [])]
        axes = [_axis_target_to_planned_axis(t) for t in (getattr(intent, "development_axes", None) or [])]
        facilities = [
            _facility_target_to_planned_facility(t) for t in (getattr(intent, "facilities", None) or [])
        ]

    # zones stays empty: zone parcel changes arrive as reclassify ParcelChanges,
    # which map to PlannedParcel, not PlannedZone.
    return PlannedState(
        version="v1",
        parcels=parcels,
        zones=[],
        facilities=facilities,
        roads=roads,
        axes=axes,
        source="parcel_change_set",
        provenance=changeset.provenance,
    )


__all__ = [
    "changeset_to_planned_state",
    "_change_to_planned_parcel",
]
