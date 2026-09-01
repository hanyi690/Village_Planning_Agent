"""Merge, geometry confirmation, and authoritative PlannedState nodes."""

from __future__ import annotations

from collections import defaultdict
import hashlib
from typing import Any, Dict, List

from app.modules.execute.execute_state import ExecuteAgentState
from app.modules.execute.workers.worker_common import (
    _execution_intent_from_plan,
    _worker_result_get,
)
from app.contracts.execute.spatial_change_contracts import (
    SpatialChangeOperation,
    SpatialChangeSet,
)


def _blocking_conflicts(diagnostics: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [item for item in diagnostics or [] if bool(item.get("blocking"))]


def _planned_state_blocked_update(
    diagnostics: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "planned_state": None,
        "execution_errors": [
            {
                "code": "planned_state_blocked_by_conflict",
                "message": (
                    "Authoritative parcel ownership conflicts must be resolved "
                    "before PlannedState is written."
                ),
                "diagnostics": diagnostics,
            }
        ],
    }


async def _merge_worker_results_node(state: ExecuteAgentState) -> dict:
    """Merge WorkerResults and erase conflicting authoritative writes."""
    from app.modules.execute.merge import merge_worker_results

    changeset, layout_configs, diagnostics, action_results = merge_worker_results(
        list(state.worker_results),
        parcel_compatibility_mode=str(
            getattr(state, "parcel_compatibility_mode", "not_applicable")
            or "not_applicable"
        ),
    )
    blockers = _blocking_conflicts(diagnostics)
    spatial_changeset = None
    if not blockers:
        try:
            spatial_changeset = _build_spatial_change_set(state.worker_results)
        except ValueError as exc:
            diagnostics.append({
                "code": "spatial_changeset_lineage_incomplete",
                "blocking": True,
                "exception_type": type(exc).__name__,
            })
            blockers = _blocking_conflicts(diagnostics)
    update: Dict[str, Any] = {
        "parcel_changeset": None if blockers else changeset,
        "spatial_changeset": None if blockers else spatial_changeset,
        "layout_configs": layout_configs,
        "worker_conflict_diagnostics": diagnostics,
        "action_results": action_results,
    }
    if changeset is not None and not blockers:
        update["parcel_changes"] = list(changeset.changes)

    if blockers:
        update.update(_planned_state_blocked_update(blockers))

    unresolved = []
    for result in state.worker_results:
        unresolved.extend(_worker_result_get(result, "unresolved_items") or [])
    if unresolved:
        update["unresolved_targets"] = (
            list(state.unresolved_targets or []) + unresolved
        )
    return update


def _build_spatial_change_set(worker_results: list[Any]) -> SpatialChangeSet | None:
    """Collect generic worker features into one deterministic change artifact."""
    by_id: dict[str, Any] = {}
    operations_by_id: dict[str, SpatialChangeOperation] = {}
    source_refs: set[str] = set()
    evidence_refs: set[str] = set()
    for result in worker_results or []:
        for feature in list(_worker_result_get(result, "scenario_features") or []):
            feature_id = str(getattr(feature, "feature_id", "") or "")
            if not feature_id:
                continue
            by_id.setdefault(feature_id, feature)
            source_refs.update(str(ref) for ref in (getattr(feature, "source_refs", None) or []) if str(ref).strip())
            evidence_refs.update(str(ref) for ref in (getattr(feature, "evidence_refs", None) or []) if str(ref).strip())
            input_operation = str(getattr(feature, "input_operation", "") or "")
            generation_operation = str(
                getattr(feature, "generation_operation", "") or ""
            )
            if not input_operation:
                raise ValueError(
                    f"spatial feature lacks approved operation: {feature_id}"
                )
            digest = str(getattr(feature, "geometry_digest", "") or "")
            if not digest:
                digest = "sha256:" + hashlib.sha256(
                    str(getattr(feature, "geometry_wkt", "") or "").encode("utf-8")
                ).hexdigest()
            operations_by_id[feature_id] = SpatialChangeOperation(
                change_ref=str(getattr(feature, "change_ref", "") or ""),
                feature_id=feature_id,
                target_ref=str(getattr(feature, "target_id", "") or ""),
                candidate_ref=str(getattr(feature, "candidate_id", "") or ""),
                operation=input_operation,
                input_operation=input_operation,
                operation_parameters=dict(
                    getattr(feature, "operation_parameters", None) or {}
                ),
                input_resource_refs=list(
                    getattr(feature, "resource_refs", None) or []
                ),
                input_representation_refs=list(
                    getattr(feature, "representation_refs", None) or []
                ),
                input_geometry_refs=list(
                    getattr(feature, "input_geometry_refs", None) or []
                ),
                source_snapshot_refs=list(
                    getattr(feature, "source_snapshot_refs", None) or []
                ),
                resource_digests=list(
                    getattr(feature, "resource_digests", None) or []
                ),
                capability_refs=list(
                    getattr(feature, "capability_refs", None) or []
                ),
                selection_refs=list(
                    getattr(feature, "selection_refs", None) or []
                ),
                approval_ref=str(getattr(feature, "approval_ref", "") or ""),
                world_model_digest=str(
                    getattr(feature, "world_model_digest", "") or ""
                ),
                input_crs=str(getattr(feature, "input_crs", "") or ""),
                output_crs=str(
                    getattr(feature, "output_crs", "")
                    or getattr(feature, "crs", "")
                    or ""
                ),
                geometry_kind=str(getattr(feature, "geometry_kind", "") or ""),
                geometry_digest=digest,
            )
    operations = [operations_by_id[key] for key in sorted(operations_by_id)]
    if not by_id:
        return None
    scenario_ids = {
        str(getattr(item, "scenario_id", "") or "")
        for item in by_id.values()
        if str(getattr(item, "scenario_id", "") or "")
    }
    if len(scenario_ids) != 1:
        raise ValueError("SpatialChangeSet requires one scenario_id")
    return SpatialChangeSet(
        features=[by_id[key] for key in sorted(by_id)],
        operations=operations,
        source_refs=sorted(source_refs),
        evidence_refs=sorted(evidence_refs),
        scenario_id=next(iter(scenario_ids)),
    )


async def _geometry_materialize_node(state: ExecuteAgentState) -> dict:
    """Confirm already-determined geometry operations without re-siting."""
    changeset = state.parcel_changeset
    diagnostics: List[Dict[str, Any]] = []
    geometry_valid = True
    checked = 0
    for change in (changeset.changes if changeset is not None else []):
        checked += 1
        if change.action in {"create", "split", "merge"} and not (
            getattr(change, "after_geometry_wkt", "") or ""
        ):
            geometry_valid = False
            diagnostics.append({
                "code": "missing_after_geometry",
                "bsm": getattr(change, "bsm", ""),
                "action": change.action,
            })
    report = {
        "geometry_valid": geometry_valid,
        "checked_changes": checked,
        "diagnostics": diagnostics,
    }
    return {"geometry_materialize_report": report}


def _layer_features(
    layout_configs: list[dict[str, Any]],
    layer_types: set[str],
):
    for layer in layout_configs or []:
        if not isinstance(layer, dict):
            continue
        layer_type = str(layer.get("layerType") or layer.get("layer_type") or "")
        if layer_type not in layer_types:
            continue
        data = layer.get("data") or layer.get("geojson") or {}
        for feature in data.get("features") or []:
            if isinstance(feature, dict):
                yield feature


def _shape_geometry(feature: dict[str, Any]):
    geometry = feature.get("geometry")
    if not isinstance(geometry, dict) or not geometry.get("type"):
        return None
    try:
        from shapely.geometry import shape

        value = shape(geometry)
        if value.is_empty or not value.is_valid:
            return None
        return value
    except Exception:
        return None


def _enrich_planned_state(
    planned_state: Any,
    layout_configs: list[dict[str, Any]],
) -> tuple[Any | None, list[dict[str, Any]]]:
    from shapely.ops import unary_union

    from app.contracts.execute.planned_state_contracts import (
        PlannedZone,
        PlannedZoneOverlay,
    )

    assignment_features = list(_layer_features(
        layout_configs,
        {"authoritative_zone_assignment"},
    ))
    assignment_by_bsm: dict[str, tuple[dict[str, Any], Any]] = {}
    diagnostics: list[dict[str, Any]] = []
    for feature in assignment_features:
        properties = dict(feature.get("properties") or {})
        bsm = str(properties.get("bsm") or "")
        geometry = _shape_geometry(feature)
        required_values = (
            properties.get("target_id"),
            properties.get("zone_id"),
            properties.get("project_ref"),
            properties.get("lineage_id"),
            properties.get("classification_system"),
            properties.get("classification_code"),
            properties.get("geometry_ref"),
        )
        if (
            not bsm
            or geometry is None
            or properties.get("materialization_role") != "land_use_assignment"
            or any(not str(value or "") for value in required_values)
        ):
            diagnostics.append({
                "code": "authoritative_assignment_layer_invalid",
                "blocking": True,
                "bsm": bsm,
            })
            continue
        if bsm in assignment_by_bsm:
            diagnostics.append({
                "code": "authoritative_assignment_layer_duplicate_bsm",
                "blocking": True,
                "bsm": bsm,
            })
            continue
        assignment_by_bsm[bsm] = (properties, geometry)

    planned_bsms = {parcel.bsm for parcel in planned_state.parcels}
    for bsm in sorted(set(assignment_by_bsm) - planned_bsms):
        diagnostics.append({
            "code": "assignment_layer_without_parcel_change",
            "blocking": True,
            "bsm": bsm,
        })
    if diagnostics:
        return None, diagnostics

    parcels = []
    for parcel in planned_state.parcels:
        entry = assignment_by_bsm.get(parcel.bsm)
        if entry is None:
            parcels.append(parcel)
            continue
        properties, _geometry = entry
        if (
            str(parcel.planning_land_use or "")
            != str(properties.get("classification_code") or "")
            or str(parcel.project_ref or "")
            != str(properties.get("project_ref") or "")
        ):
            diagnostics.append({
                "code": "assignment_layer_change_mismatch",
                "blocking": True,
                "bsm": parcel.bsm,
            })
            continue
        parcels.append(parcel.model_copy(update={
            "project_ref": str(properties.get("project_ref") or ""),
            "target_ref": str(properties.get("target_id") or ""),
            "derived_from_zone_target": str(properties.get("target_id") or ""),
            "lineage_id": str(properties.get("lineage_id") or ""),
            "claim_refs": list(properties.get("claim_refs") or []),
            "source_instruction_id": str(
                properties.get("source_instruction_id") or ""
            ),
            "source_report_key": str(properties.get("source_report_key") or ""),
            "geometry_ref": str(properties.get("geometry_ref") or ""),
            "classification_system": str(
                properties.get("classification_system") or ""
            ),
            "classification_code": str(
                properties.get("classification_code") or ""
            ),
            "zone_type": str(properties.get("zone_id") or ""),
        }))

    if diagnostics:
        return None, diagnostics

    zone_groups: dict[str, list[tuple[str, dict[str, Any], Any]]] = defaultdict(list)
    for bsm, (properties, geometry) in assignment_by_bsm.items():
        zone_id = str(
            properties.get("zone_id")
            or properties.get("target_id")
            or ""
        )
        zone_groups[zone_id].append((bsm, properties, geometry))

    zones = []
    for zone_id, entries in sorted(zone_groups.items()):
        first = entries[0][1]
        signatures = {
            (
                str(item[1].get("target_id") or ""),
                str(item[1].get("project_ref") or ""),
                str(item[1].get("classification_system") or ""),
                str(item[1].get("classification_code") or ""),
                str(item[1].get("planning_land_use") or ""),
            )
            for item in entries
        }
        if len(signatures) != 1:
            diagnostics.append({
                "code": "authoritative_zone_group_inconsistent",
                "blocking": True,
                "zone_id": zone_id,
                "bsms": sorted(item[0] for item in entries),
            })
            continue
        unioned = unary_union([entry[2] for entry in entries])
        target_id = str(first.get("target_id") or "")
        zones.append(PlannedZone(
            zone_id=zone_id,
            zone_type=zone_id,
            planning_land_use=str(first.get("planning_land_use") or ""),
            classification_system=str(first.get("classification_system") or ""),
            classification_code=str(first.get("classification_code") or ""),
            area_ha=round(sum(float(item[1].get("area_ha") or 0) for item in entries), 6),
            name=str(first.get("planning_land_use") or zone_id),
            geometry=unioned.wkt,
            derived_from_zone_target=target_id,
            target_ref=target_id,
            project_ref=str(first.get("project_ref") or ""),
            parcel_bsms=sorted(item[0] for item in entries),
            lineage_ids=sorted(
                str(item[1].get("lineage_id") or "")
                for item in entries
                if str(item[1].get("lineage_id") or "")
            ),
            claim_refs=sorted({
                str(claim_ref)
                for item in entries
                for claim_ref in item[1].get("claim_refs") or []
                if str(claim_ref)
            }),
        ))

    if diagnostics:
        return None, diagnostics

    overlay_types = {
        "functional_zone_overlay",
        "protection_overlay",
        "restoration_overlay",
    }
    # Global zone allocation also carries the complete protection/restoration
    # constraint inventory.  Only overlays that were selected into the
    # scenario's authoritative planned_project/planned_zone layers belong in
    # PlannedState; the remaining constraint geometries stay upstream as
    # suitability/constraint evidence and must not become orphan scenario
    # features at VALIDATE.
    selected_overlay_targets = {
        str(value)
        for overlay in (getattr(planned_state, "overlays", None) or [])
        for value in (
            getattr(overlay, "overlay_id", ""),
            getattr(overlay, "target_ref", ""),
            getattr(overlay, "project_ref", ""),
            getattr(overlay, "feature_id", ""),
            getattr(overlay, "candidate_id", ""),
        )
        if str(value or "").strip()
    }
    overlay_groups: dict[tuple[str, str], list[tuple[str, dict[str, Any], Any]]] = (
        defaultdict(list)
    )
    for feature in _layer_features(layout_configs, overlay_types):
        properties = dict(feature.get("properties") or {})
        role = str(properties.get("materialization_role") or "")
        target_id = str(properties.get("target_id") or "")
        bsm = str(properties.get("bsm") or "")
        geometry = _shape_geometry(feature)
        if role not in {
            "functional_overlay",
            "protection_overlay",
            "restoration_overlay",
        } or not target_id or geometry is None:
            diagnostics.append({
                "code": "zone_overlay_layer_invalid",
                "blocking": True,
                "target_id": target_id,
                "bsm": bsm,
            })
            continue
        feature_candidate_id = str(properties.get("candidate_id") or "")
        if selected_overlay_targets and not (
            target_id in selected_overlay_targets
            or feature_candidate_id in selected_overlay_targets
        ):
            continue
        overlay_groups[(role, target_id)].append((bsm, properties, geometry))
    if diagnostics:
        return None, diagnostics

    # Keep the selected candidate-backed overlays that were already produced
    # from ``planned_project``.  The raw overlay layers are a constraint
    # inventory, not an implicit selection source; they are only considered
    # when a selected target explicitly exists in the authoritative state.
    overlays = list(getattr(planned_state, "overlays", None) or [])
    for (role, target_id), entries in sorted(overlay_groups.items()):
        if not selected_overlay_targets:
            continue
        if target_id in selected_overlay_targets:
            # The selected candidate geometry already lives in planned_state;
            # do not replace it with the broader baseline overlay union.
            continue
        unioned = unary_union([entry[2] for entry in entries])
        first = entries[0][1]
        overlays.append(PlannedZoneOverlay(
            overlay_id=target_id,
            materialization_role=role,
            name=str(first.get("category_code") or target_id),
            geometry=unioned.wkt,
            target_ref=target_id,
            project_ref=str(first.get("project_ref") or ""),
            derived_from_bsms=sorted({
                item[0] for item in entries if item[0]
            }),
            lineage_refs=sorted({
                str(item[1].get("lineage_id") or "")
                for item in entries
                if str(item[1].get("lineage_id") or "")
            }),
            provenance_refs=sorted({
                str(ref)
                for item in entries
                for ref in item[1].get("provenance_refs") or []
                if str(ref)
            }),
        ))

    return planned_state.model_copy(update={
        "parcels": parcels,
        "zones": zones,
        "overlays": overlays,
    }), []


async def _planned_state_builder_node(state: ExecuteAgentState) -> dict:
    """Produce PlannedState only when authoritative ownership is conflict-free."""
    from app.modules.execute.planned_state_builder import (
        changeset_to_planned_state,
    )

    blockers = _blocking_conflicts(list(state.worker_conflict_diagnostics or []))
    if blockers:
        return _planned_state_blocked_update(blockers)
    scenario_features = list(
        getattr(getattr(state, "spatial_changeset", None), "features", None)
        or [
            feature
            for result in list(state.worker_results or [])
            for feature in list(_worker_result_get(result, "scenario_features") or [])
        ]
    )
    if state.parcel_changeset is None and not scenario_features:
        return {}
    planned_state = changeset_to_planned_state(
        state.parcel_changeset,
        _execution_intent_from_plan(state),
        list(state.layout_configs or []),
        scenario_features=scenario_features,
    )
    enriched, diagnostics = _enrich_planned_state(
        planned_state,
        list(state.layout_configs or []),
    )
    if diagnostics:
        return _planned_state_blocked_update(diagnostics)
    scenario_features = list(getattr(enriched, "features", None) or [])
    scenario_id = str(
        getattr(getattr(state, "execution_plan", None), "scenario_id", "")
        or getattr(getattr(state, "approved_execution_input", None), "scenario_id", "")
        or ""
    )
    if not scenario_id and scenario_features:
        scenario_id = str(getattr(scenario_features[0], "scenario_id", "") or "")
    scenario_ref = str(getattr(state, "scenario_ref", "") or "")
    trace_refs = [
        f"trace:{item.get('task_id')}:{item.get('event')}"
        for item in list(state.execution_trace or [])
        if item.get("task_id") and item.get("event")
    ]
    enriched = enriched.model_copy(update={
        "scenario_id": scenario_id,
        "scenario_ref": scenario_ref,
        "execution_trace_refs": list(dict.fromkeys(trace_refs)),
    })
    return {"planned_state": enriched}


__all__ = [
    "_geometry_materialize_node",
    "_merge_worker_results_node",
    "_planned_state_builder_node",
]
