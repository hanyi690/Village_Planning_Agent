"""EXECUTE review package builder - plain serializable dict.

Pure function: ParcelChangeSet + PlannedState -> dict. No I/O.
Mirrors the ground/select review convention (Chinese section headers,
pydantic models dumped to JSON-safe values). Deterministic only.
"""
from __future__ import annotations

from typing import Any

from shapely import wkt as shapely_wkt
from shapely.geometry import mapping

from app.modules.schema.contracts.parcel_change_contracts import ParcelChange, ParcelChangeSet
from app.modules.schema.contracts.planned_state_contracts import PlannedState


def _context_parcels(context: Any) -> dict[str, Any]:
    if isinstance(context, dict):
        parcels = context.get("parcel_by_bsm")
        if isinstance(parcels, dict):
            return parcels
    return {}


def _build_operation_log(changeset: ParcelChangeSet) -> dict[str, Any]:
    by_action: dict[str, int] = {}
    for change in changeset.changes:
        by_action[change.action] = by_action.get(change.action, 0) + 1
    return {"total": len(changeset.changes), "by_action": by_action}


def _build_area_conservation(changeset: ParcelChangeSet) -> dict[str, Any]:
    return {
        "area_conservation_verified": changeset.area_conservation_verified,
        "geometry_validity_verified": changeset.geometry_validity_verified,
        "changes": len(changeset.changes),
    }


def _build_parcel_lineage(changeset: ParcelChangeSet) -> list[dict[str, Any]]:
    return [
        {
            "bsm": change.bsm,
            "action": change.action,
            "derived_from_bsms": list(change.derived_from_bsms),
            "before_classification_code": (
                change.before_classification.code if change.before_classification else ""
            ),
            "after_classification_code": (
                change.after_classification.code if change.after_classification else ""
            ),
        }
        for change in changeset.changes
    ]


def _build_planned_state_summary(planned_state: PlannedState) -> dict[str, Any]:
    return {
        "parcels": len(planned_state.parcels),
        "zones": len(planned_state.zones),
        "facilities": len(planned_state.facilities),
        "roads": len(planned_state.roads),
        "axes": len(planned_state.axes),
        "version": planned_state.version,
        "source": planned_state.source,
    }


def _build_facility_road_axis_listing(planned_state: PlannedState) -> dict[str, Any]:
    return {
        "facilities": [
            {
                "name": f.name,
                "facility_type": f.facility_type,
                "lon": f.lon,
                "lat": f.lat,
            }
            for f in planned_state.facilities
        ],
        "roads": [
            {"name": r.name, "road_level": r.road_level, "width_m": r.width_m}
            for r in planned_state.roads
        ],
        "axes": [
            {
                "name": a.name,
                "reference_feature": a.reference_feature,
                "direction": a.direction,
            }
            for a in planned_state.axes
        ],
    }


def _build_provenance(changeset: ParcelChangeSet) -> dict[str, Any]:
    if changeset.provenance is None:
        return {}
    return changeset.provenance.model_dump(mode="json")


def build_before_after_geojson(
    changeset: ParcelChangeSet, parcel_by_bsm: dict[str, dict] | None = None
) -> dict[str, Any]:
    """Build a GeoJSON FeatureCollection of before/after parcel geometries.

    ONE feature per change carrying both WKTs in properties plus the after
    geometry. Geometry resolves from after_geometry_wkt first, then falls back
    to parcel_by_bsm; changes with no resolvable geometry are skipped.
    """
    properties = {"note": "EXECUTE before/after parcel comparison"}
    parcel_by_bsm = parcel_by_bsm or {}
    features = []
    for change in changeset.changes:
        geometry = None
        if change.after_geometry_wkt:
            try:
                geometry = mapping(shapely_wkt.loads(change.after_geometry_wkt))
            except Exception:
                geometry = None
        if geometry is None:
            geometry = parcel_by_bsm.get(change.bsm, {}).get("geometry")
        if geometry is None:
            continue
        features.append(
            {
                "type": "Feature",
                "properties": {
                    "bsm": change.bsm,
                    "action": change.action,
                    "before_geometry_wkt": change.before_geometry_wkt,
                    "after_geometry_wkt": change.after_geometry_wkt,
                    "derived_from_bsms": list(change.derived_from_bsms),
                },
                "geometry": geometry,
            }
        )
    return {"type": "FeatureCollection", "features": features, "properties": properties}


def build_execute_review_package(
    changeset: ParcelChangeSet,
    planned_state: PlannedState,
    *,
    context: Any = None,
) -> dict[str, Any]:
    """Construct the EXECUTE review package content dict (pure, no I/O).

    context may carry {"parcel_by_bsm": {...}} to supply fallback geometry
    for the before/after map; defaults to an empty lookup.
    """
    return {
        "操作日志": _build_operation_log(changeset),
        "面积守恒": _build_area_conservation(changeset),
        "地块谱系": _build_parcel_lineage(changeset),
        "前后对比图": build_before_after_geojson(changeset, _context_parcels(context)),
        "PlannedState 摘要": _build_planned_state_summary(planned_state),
        "设施/道路/轴线清单": _build_facility_road_axis_listing(planned_state),
        "未解析目标": {
            "count": 0,
            "note": "unresolved tracking deferred to Wave J/VALIDATE",
        },
        "来源追溯": _build_provenance(changeset),
    }


__all__ = ["build_execute_review_package", "build_before_after_geojson"]
