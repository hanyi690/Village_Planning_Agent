"""ZONING stage - synthesize planning zones from remaining parcels.

Wave Z: runs between EXECUTE and VALIDATE in the post-L3 chain. EXECUTE
skips zone targets whose ``candidate_bsms`` is empty (see
``_execute_layout_node`` in execute_agent.py), so those zones produce no
geometry. This stage fills the gap: it assigns the remaining unoccupied
land-use parcels to zone targets without candidates and produces
reclassify ParcelChanges plus a planning_zones layer. Unclaimed parcels
are tagged preserve (prohibited constraint) or unassigned.

Deterministic; no LLM, no KG, no MIP.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.agent.bootstrap.post_l3_state import PostL3ChainState
from app.agent.validate.checks import _PROHIBITED_CONSTRAINTS
from app.modules.schema.contracts.classification_ref import ClassificationRef
from app.modules.schema.contracts.parcel_change_contracts import (
    ParcelChange,
    ParcelChangeSet,
)

# ZoneAssignment.source allowed values.
SOURCE_ZONE_TARGET = "zone_target"
SOURCE_L2_STRUCTURE = "l2_structure"
SOURCE_PRESERVE = "preserve"
SOURCE_UNASSIGNED = "unassigned"

_OCCUPYING_ACTIONS = ("create", "merge", "reclassify")


class ZoneAssignment(BaseModel):
    """One parcel -> planning zone assignment produced by the ZONING stage."""

    bsm: str
    zone: str = ""  # land_use label
    zone_id: str = ""
    source: str = SOURCE_ZONE_TARGET
    land_use_code: str = ""


def _resolve_context(state: PostL3ChainState) -> Any:
    """Return the live PlanningContext for a chain run (mirrors post_l3_nodes).

    With a checkpointer, ``context`` is stripped from the serialized state, so
    fall back to the session context cache when ``state.context`` is absent.
    """
    context = getattr(state, "context", None)
    if context is not None:
        return context
    if getattr(state, "session_id", ""):
        try:
            from app.services.context.planning_context import get_cached_context

            return get_cached_context(state.session_id)
        except Exception:
            return None
    return None


def _geometry_to_wkt(geometry: Any) -> str:
    """Convert a GeoJSON geometry dict to WKT; return "" for invalid geometry."""
    if not isinstance(geometry, dict):
        return ""
    try:
        from shapely.geometry import shape

        return shape(geometry).wkt
    except Exception:
        return ""


def _parcel_area_ha(parcel: Any) -> float:
    area_sqm = float(getattr(parcel, "area_sqm", 0) or 0)
    if area_sqm <= 0:
        area_sqm = float(getattr(parcel, "area_ha", 0) or 0) * 10000
    return area_sqm / 10000.0


def _parcel_centroid(parcel: Any) -> tuple[float, float]:
    try:
        from shapely.geometry import shape

        geom = shape(getattr(parcel, "geometry", None) or {})
        c = geom.centroid
        return (float(c.x), float(c.y))
    except Exception:
        return (0.0, 0.0)


def _order_by_preference(parcels: list, spatial_preference: Any) -> list:
    """Sort candidates by spatial_preference.direction (north/south/east/west).

    North = highest centroid y first; south = lowest first; east = highest x;
    west = lowest x. Without a usable direction, keep bundle order.
    """
    direction = ""
    if spatial_preference is not None:
        direction = str(getattr(spatial_preference, "direction", "") or "").lower()
    if direction not in ("north", "south", "east", "west"):
        return list(parcels)
    if direction == "north":
        return sorted(parcels, key=lambda p: -_parcel_centroid(p)[1])
    if direction == "south":
        return sorted(parcels, key=lambda p: _parcel_centroid(p)[1])
    if direction == "east":
        return sorted(parcels, key=lambda p: -_parcel_centroid(p)[0])
    return sorted(parcels, key=lambda p: _parcel_centroid(p)[0])


def _zone_code(zone_target: Any) -> str:
    return str(zone_target.vne_code or "") or str(zone_target.land_use or "")


def _reclassify_change(parcel: Any, zone_target: Any) -> ParcelChange:
    """Build a reclassify ParcelChange for a parcel assigned to a zone."""
    bsm = str(getattr(parcel, "bsm", ""))
    wkt = _geometry_to_wkt(getattr(parcel, "geometry", None))
    return ParcelChange(
        bsm=bsm,
        action="reclassify",
        derived_from_bsms=[bsm],
        after_classification=ClassificationRef(
            system="ghytbm",
            code=_zone_code(zone_target),
            canonical_name=str(zone_target.land_use or ""),
            source="derived",
        ),
        before_geometry_wkt=wkt,
        after_geometry_wkt=wkt,
        new_area_ha=_parcel_area_ha(parcel),
        project_ref=f"zone:{zone_target.zone_id or zone_target.land_use}",
        intervention_id=zone_target.zone_id or "",
    )


def _overlaps_prohibited(parcel: Any, constraint_index: Any) -> bool:
    geometry = getattr(parcel, "geometry", None)
    if not isinstance(geometry, dict):
        return False
    try:
        overlaps = constraint_index.geometry_in_constraint(geometry) or []
    except Exception:
        return False
    return any(
        getattr(ov, "constraint_type", "") in _PROHIBITED_CONSTRAINTS
        for ov in overlaps
    )


def zoning_aggregate(
    intent: Any,
    parcel_changeset: Any,
    context: Any,
) -> tuple[list[ZoneAssignment], list[ParcelChange]]:
    """Assign remaining parcels to zone targets; return (assignments, changes).

    ``occupied_bsms`` are the project footprints + zones EXECUTE already
    reclassified (create/merge/reclassify changes). Zone targets with existing
    ``candidate_bsms`` are already handled by EXECUTE; only their assignments
    are recorded. Zone targets with empty ``candidate_bsms`` (the broken
    default path) claim the remaining unoccupied land-use parcels up to their
    ``area_ha`` target. Remaining unclaimed parcels are tagged preserve
    (prohibited constraint) or unassigned.
    """
    assignments: list[ZoneAssignment] = []
    new_zone_changes: list[ParcelChange] = []
    if intent is None:
        return assignments, new_zone_changes

    occupied_bsms = {
        str(getattr(change, "bsm", ""))
        for change in (parcel_changeset.changes if parcel_changeset is not None else [])
        if getattr(change, "action", "") in _OCCUPYING_ACTIONS
    }

    bundle = getattr(context, "bundle", None)
    landuse: list[Any] = []
    if bundle is not None and hasattr(bundle, "polygons"):
        landuse = list(bundle.polygons.get("landuse_current") or [])
    candidates = [
        p
        for p in landuse
        if str(getattr(p, "bsm", "")) and str(getattr(p, "bsm", "")) not in occupied_bsms
    ]

    zone_targets = getattr(intent, "zone_targets", None)
    if zone_targets is None and isinstance(intent, dict):
        zone_targets = intent.get("zone_targets")
    zone_targets = list(zone_targets or [])

    claimed_bsms: set[str] = set()

    for zone_target in zone_targets:
        zone_bsms = [str(b) for b in (zone_target.candidate_bsms or []) if str(b)]
        code = _zone_code(zone_target)
        if zone_bsms:
            for bsm in zone_bsms:
                assignments.append(
                    ZoneAssignment(
                        bsm=bsm,
                        zone=str(zone_target.land_use or ""),
                        zone_id=zone_target.zone_id,
                        source=SOURCE_ZONE_TARGET,
                        land_use_code=code,
                    )
                )
            claimed_bsms.update(zone_bsms)
            continue

        available = [
            p for p in candidates if str(getattr(p, "bsm", "")) not in claimed_bsms
        ]
        ordered = _order_by_preference(available, zone_target.spatial_preference)
        target_ha = zone_target.area_ha
        accumulated = 0.0
        assigned: list[Any] = []
        for parcel in ordered:
            bsm = str(getattr(parcel, "bsm", ""))
            if bsm in claimed_bsms:
                continue
            assigned.append(parcel)
            claimed_bsms.add(bsm)
            accumulated += _parcel_area_ha(parcel)
            if target_ha is not None and accumulated >= target_ha:
                break

        for parcel in assigned:
            bsm = str(getattr(parcel, "bsm", ""))
            new_zone_changes.append(_reclassify_change(parcel, zone_target))
            if zone_target.candidate_bsms is None:
                zone_target.candidate_bsms = []
            zone_target.candidate_bsms.append(bsm)
            assignments.append(
                ZoneAssignment(
                    bsm=bsm,
                    zone=str(zone_target.land_use or ""),
                    zone_id=zone_target.zone_id,
                    source=SOURCE_ZONE_TARGET,
                    land_use_code=code,
                )
            )

    constraint_index = getattr(context, "constraint_index", None)
    for parcel in candidates:
        bsm = str(getattr(parcel, "bsm", ""))
        if bsm in claimed_bsms or bsm in occupied_bsms:
            continue
        zone = "待定/其他"
        source = SOURCE_UNASSIGNED
        if constraint_index is not None and _overlaps_prohibited(parcel, constraint_index):
            zone = "生态保护/保留"
            source = SOURCE_PRESERVE
        assignments.append(
            ZoneAssignment(
                bsm=bsm,
                zone=zone,
                source=source,
            )
        )

    return assignments, new_zone_changes


def _zone_layer(zone_changes: list[ParcelChange]) -> dict | None:
    """Build the planning_zones layer from reclassified ParcelChange entries.

    Mirrors execute_agent._function_zone_layer shape with a distinct
    planning_zones layer type.
    """
    from shapely import wkt
    from shapely.geometry import mapping as geometry_mapping

    features = []
    for change in zone_changes:
        if getattr(change, "action", "") != "reclassify":
            continue
        geometry = {}
        after_wkt = getattr(change, "after_geometry_wkt", "") or ""
        if after_wkt:
            try:
                geom = wkt.loads(after_wkt)
                if not geom.is_empty:
                    geometry = geometry_mapping(geom)
            except Exception:
                geometry = {}
        if not geometry:
            continue
        cls = getattr(change, "after_classification", None)
        bsm = str(getattr(change, "bsm", ""))
        features.append(
            {
                "type": "Feature",
                "properties": {
                    "bsm": bsm,
                    "planning_land_use": str(getattr(cls, "code", "") or ""),
                    "zone_type": str(getattr(cls, "canonical_name", "") or ""),
                    "action": getattr(change, "action", ""),
                    "source_bsm": bsm,
                    "area_ha": round(float(getattr(change, "new_area_ha", 0) or 0), 2),
                },
                "geometry": geometry,
            }
        )
    if not features:
        return None
    return {
        "layerType": "planning_zones",
        "layerName": "规划分区",
        "data": {"type": "FeatureCollection", "features": features},
    }


async def zoning_node(state: PostL3ChainState) -> dict[str, Any]:
    """ZONING node: assign remaining parcels to zones, extend the changeset.

    Returns zone_assignments plus (when zone changes were produced) a rebuilt
    parcel_changeset and a planning_zones layer. Never raises when
    ``state.parcel_changeset`` is None — just returns assignments.
    """
    context = _resolve_context(state)
    intent = getattr(state, "intent", None)
    assignments: list[ZoneAssignment] = []
    new_zone_changes: list[ParcelChange] = []
    if intent is not None:
        assignments, new_zone_changes = zoning_aggregate(
            intent, state.parcel_changeset, context
        )

    result: dict[str, Any] = {"zone_assignments": assignments}
    if state.parcel_changeset is None:
        return result

    if new_zone_changes:
        result["parcel_changeset"] = ParcelChangeSet(
            changes=[*list(state.parcel_changeset.changes), *new_zone_changes],
            area_conservation_verified=state.parcel_changeset.area_conservation_verified,
            geometry_validity_verified=state.parcel_changeset.geometry_validity_verified,
        )
        zone_layer = _zone_layer(new_zone_changes)
        if zone_layer is not None:
            result["layout_configs"] = [
                *list(state.layout_configs or []),
                zone_layer,
            ]
    else:
        result["parcel_changeset"] = state.parcel_changeset
    return result


__all__ = [
    "ZoneAssignment",
    "zoning_aggregate",
    "zoning_node",
]
