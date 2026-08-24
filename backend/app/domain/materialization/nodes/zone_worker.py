"""Zone worker: materialize audited global assignments and independent overlays."""

from __future__ import annotations

from typing import Any, Dict, List

from app.contracts.workflow.execution_plan_contracts import WorkerResult
from app.domain.materialization.execute_state import ExecuteAgentState
from app.domain.materialization.nodes.worker_common import (
    _execution_intent_from_plan,
    _intent_list,
    _resolve_parcel_by_bsm,
    _candidate_availability_block,
    _scenario_features_for_layer,
    _task_enabled,
    _task_execution_result,
)

def _parcel_geometry(parcel: Any) -> dict:
    geometry = (
        parcel.get("geometry")
        if isinstance(parcel, dict)
        else getattr(parcel, "geometry", None)
    )
    try:
        from shapely.geometry import mapping, shape

        if isinstance(geometry, dict) and geometry.get("type"):
            value = shape(geometry)
        elif hasattr(geometry, "__geo_interface__"):
            value = shape(geometry.__geo_interface__)
        else:
            return {}
        if value.is_empty or not value.is_valid:
            return {}
        return dict(mapping(value))
    except Exception:
        return {}


def _repair_skip_bsms(state: ExecuteAgentState, target_id: str) -> set[str]:
    """Return BSMs a VALIDATE repair directive asks zone materialization to drop.

    ``rebuild_geometry`` / ``exclude_bsms`` directives for a zone target carry
    the offending parcels; materializing them again would reproduce the same
    invalid/overlapping geometry.  Skipped parcels stay preserved instead of
    being silently merged, and are surfaced as explicit diagnostics.
    """
    entry = (state.repair_directives or {}).get(str(target_id))
    if not entry:
        return set()
    skip = set(entry.get("affected_bsms") or [])
    skip.update(entry.get("exclude_bsms") or [])
    return skip


def _custom_zone_targets_from_plan(
    state: ExecuteAgentState,
) -> tuple[List[Any], List[Any]]:
    """Restore explicit custom functional-overlay targets from task bindings."""
    from app.contracts.domain.custom_zone_contracts import CustomZoneTarget

    targets: List[Any] = []
    invalid_tasks: List[Any] = []
    for task in list(getattr(state.execution_plan, "worker_tasks", None) or []):
        if str(getattr(task, "target_type", "") or "") != "zone":
            continue
        assignment = getattr(task, "assignment", None)
        binding = getattr(assignment, "target_binding", {}) or {}
        if not isinstance(binding, dict):
            continue
        if not binding.get("category_code") or not binding.get("vocabulary_name"):
            continue
        try:
            targets.append(CustomZoneTarget.model_validate(binding))
        except (TypeError, ValueError):
            invalid_tasks.append(task)
    return targets, invalid_tasks


def _functional_overlay_layer(
    custom_targets: list[Any],
    parcel_by_bsm: Dict[str, Any],
) -> tuple[dict | None, list[dict[str, Any]], set[str]]:
    features: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    succeeded: set[str] = set()
    for target in sorted(custom_targets, key=lambda item: str(item.target_id)):
        decision = getattr(target, "classification_decision", None)
        if (
            decision is None
            or str(getattr(decision, "status", "") or "") != "resolved"
            or str(getattr(decision, "target_id", "") or "")
            != str(target.target_id)
        ):
            unresolved.append({
                "code": "classification_invalid",
                "target_id": str(target.target_id),
            })
            continue
        target_ok = True
        target_features: list[dict[str, Any]] = []
        for bsm in sorted(set(getattr(target, "target_bsms", None) or [])):
            geometry = _parcel_geometry(parcel_by_bsm.get(bsm))
            if not geometry:
                target_ok = False
                unresolved.append({
                    "code": "functional_overlay_parcel_missing",
                    "target_id": str(target.target_id),
                    "bsm": bsm,
                })
                continue
            target_features.append({
                "type": "Feature",
                "properties": {
                    "target_id": str(target.target_id),
                    "project_ref": str(target.target_id),
                    "bsm": bsm,
                    "materialization_role": "functional_overlay",
                    "vocabulary_name": str(target.vocabulary_name),
                    "category_code": str(target.category_code),
                    "provenance_refs": [f"custom-zone:{target.target_id}"],
                },
                "geometry": geometry,
            })
        if target_ok and getattr(target, "target_bsms", None):
            features.extend(target_features)
            succeeded.add(str(target.target_id))
    layer = None
    if features:
        layer = {
            "layerType": "functional_zone_overlay",
            "layerName": "功能分区叠加层",
            "data": {"type": "FeatureCollection", "features": features},
        }
    return layer, unresolved, succeeded


def _zone_worker(
    state: ExecuteAgentState,
) -> WorkerResult:
    """Materialize only approval-bound task geometry and functional overlays."""

    if not _task_enabled(state, "layout"):
        return WorkerResult(worker_type="zone")

    custom_targets, invalid_custom_tasks = _custom_zone_targets_from_plan(state)
    custom_ids = {str(target.target_id) for target in custom_targets}
    invalid_custom_ids = {
        str(getattr(task, "target_id", "") or "")
        for task in invalid_custom_tasks
    }
    custom_task_ids = custom_ids | invalid_custom_ids
    intent_state = state
    if custom_task_ids and state.execution_plan is not None:
        plan = state.execution_plan.model_copy(update={
            "worker_tasks": [
                task
                for task in state.execution_plan.worker_tasks
                if str(getattr(task, "target_id", "") or "")
                not in custom_task_ids
            ]
        })
        intent_state = state.model_copy(update={"execution_plan": plan})
    bound_intent = _execution_intent_from_plan(intent_state)
    zone_targets = [
        target
        for target in _intent_list(bound_intent, "zone_targets")
        if str(getattr(target, "target_id", "") or "") not in custom_ids
    ]
    # A relation-aware zone may be backed by an execution polygon rather than
    # an authoritative parcel allocation.  Materialize that typed geometry
    # directly.  A candidate-bound target that is not executable is deferred;
    # it must never be widened into a whole BSM by the allocation branch.
    direct_targets: list[Any] = []
    blocked_targets: list[Any] = []
    direct_layers: list[dict[str, Any]] = []
    direct_features: list[dict[str, Any]] = []
    blocked_unresolved: list[dict[str, Any]] = []
    candidate_map = getattr(state, "candidate_geometry_by_id", {}) or {}
    from shapely import wkt as shapely_wkt
    from shapely.geometry import mapping as shapely_mapping
    for task in list(getattr(state.execution_plan, "worker_tasks", None) or []):
        if str(getattr(task, "target_type", "") or "") != "zone":
            continue
        candidate_id = str(getattr(task, "candidate_id", "") or "")
        if not candidate_id:
            continue
        candidate = candidate_map.get(candidate_id)
        target = next((item for item in zone_targets if str(getattr(item, "target_id", "")) == str(getattr(task, "target_id", ""))), None)
        if target is None:
            continue
        if candidate is None:
            blocked_targets.append(target)
            blocked_unresolved.append({
                "code": "candidate_geometry_missing",
                "target_id": str(target.target_id),
                "candidate_id": candidate_id,
                "message": "Zone execution requires the selected candidate geometry artifact.",
            })
            continue
        availability_block = _candidate_availability_block(candidate)
        if availability_block:
            blocked_targets.append(target)
            blocked_unresolved.append({
                "code": availability_block,
                "target_id": str(target.target_id),
                "candidate_id": candidate_id,
                "message": "Zone execution candidate has no executable availability proof.",
            })
            continue
        candidate_role = str(getattr(candidate, "role", "") or "")
        candidate_wkt = str(getattr(candidate, "wkt", "") or "").strip()
        if candidate_role != "execution_geometry" or not candidate_wkt:
            blocked_targets.append(target)
            blocked_unresolved.append({
                "code": "candidate_geometry_not_executable",
                "target_id": str(target.target_id),
                "candidate_id": candidate_id,
                "candidate_role": candidate_role,
                "message": "Zone candidate is a scope/corridor/parcel candidate, not execution geometry.",
            })
            continue
        try:
            parsed_geometry = shapely_wkt.loads(candidate_wkt)
            if parsed_geometry.is_empty or not parsed_geometry.is_valid:
                raise ValueError("empty_or_invalid_geometry")
            geometry = shapely_mapping(parsed_geometry)
        except Exception as exc:
            blocked_targets.append(target)
            blocked_unresolved.append({
                "code": "candidate_geometry_invalid",
                "target_id": str(target.target_id),
                "candidate_id": candidate_id,
                "message": "Zone execution candidate geometry could not be parsed.",
                "exception_type": type(exc).__name__,
            })
            continue
        direct_targets.append(target)
        direct_features.append({
            "type": "Feature",
            "properties": {
                "target_id": str(target.target_id),
                "project_ref": str(target.target_id),
                "candidate_id": candidate_id,
                "source_bsms": list(getattr(candidate, "source_bsms", None) or []),
                "feature_bsms": list(getattr(candidate, "feature_bsms", None) or []),
                "source_feature_ids": list(
                    getattr(candidate, "source_feature_ids", None) or []
                ),
                "entity_refs": list(getattr(candidate, "entity_refs", None) or []),
                "relation_refs": list(getattr(candidate, "relation_refs", None) or []),
                "evidence_refs": list(getattr(candidate, "evidence_refs", None) or []),
                "l1_snapshot_ref": str(
                    getattr(candidate, "l1_snapshot_ref", "") or ""
                ),
                "bundle_snapshot_digest": str(
                    getattr(candidate, "bundle_snapshot_digest", "") or ""
                ),
                "subgeometry_operation": str(
                    getattr(candidate, "subgeometry_operation", "") or ""
                ),
                "subgeometry_diagnostics": list(
                    getattr(candidate, "subgeometry_diagnostics", None) or []
                ),
                "source_area_ha": getattr(candidate, "source_area_ha", None),
                "planning_area_ha": getattr(candidate, "planning_area_ha", None),
                "coverage_ratio": getattr(candidate, "coverage_ratio", None),
                "availability_status": str(
                    getattr(candidate, "availability_status", "unknown") or "unknown"
                ),
                "eligible_area_ha": getattr(candidate, "eligible_area_ha", None),
                "excluded_area_ha": getattr(candidate, "excluded_area_ha", None),
                "adjacent_parcel_bsms": list(
                    getattr(candidate, "adjacent_parcel_bsms", None) or []
                ),
                "adjacency_evidence_refs": list(
                    getattr(candidate, "adjacency_evidence_refs", None) or []
                ),
                "scenario_id": str(getattr(task, "scenario_id", "") or ""),
                "source_refs": list(dict.fromkeys([
                    *list(getattr(candidate, "source_refs", None) or []),
                    *list(getattr(candidate, "evidence_refs", None) or []),
                    str(getattr(candidate, "source_ref", "") or ""),
                ])) or ["candidate_geometry"],
                "generation_operation": "candidate_geometry_materialize",
                "materialization_role": "land_use_assignment",
                "hard_constraint_status": str(
                    getattr(candidate, "hard_constraint_status", "") or ""
                ),
            },
            "geometry": geometry,
        })
    if direct_features:
        direct_layers.append({
            "layerType": "planned_zone",
            "layerName": "规划功能分区",
            "data": {"type": "FeatureCollection", "features": direct_features},
        })
    direct_ids = {str(getattr(item, "target_id", "")) for item in direct_targets}
    blocked_ids = {str(getattr(item, "target_id", "")) for item in blocked_targets}
    zone_targets = [
        item
        for item in zone_targets
        if str(getattr(item, "target_id", "")) not in direct_ids
        and str(getattr(item, "target_id", "")) not in blocked_ids
    ]
    parcel_by_bsm = _resolve_parcel_by_bsm(state)
    diagnostics: List[Dict[str, Any]] = []
    unresolved: List[Dict[str, Any]] = []
    task_statuses: Dict[str, str] = {}
    layers: list[dict[str, Any]] = list(direct_layers)
    unresolved.extend(blocked_unresolved)
    for target in direct_targets:
        task_statuses[str(target.target_id)] = "succeeded"
    for target in blocked_targets:
        task_statuses[str(target.target_id)] = "deferred"

    functional_layer, functional_unresolved, functional_succeeded = (
        _functional_overlay_layer(custom_targets, parcel_by_bsm)
    )
    unresolved.extend(functional_unresolved)
    if functional_layer is not None:
        layers.append(functional_layer)
    for target in custom_targets:
        target_id = str(target.target_id)
        task_statuses[target_id] = (
            "succeeded" if target_id in functional_succeeded else "failed"
        )
    for task in invalid_custom_tasks:
        target_id = str(getattr(task, "target_id", "") or "")
        task_statuses[target_id] = "failed"
        unresolved.append({
            "code": "custom_zone_binding_invalid",
            "target_id": target_id,
        })

    zone_changes: list[Any] = []
    scheduled_zone_ids = {
        str(getattr(task, "target_id", "") or "")
        for task in list(getattr(state.execution_plan, "worker_tasks", None) or [])
        if str(getattr(task, "target_type", "") or "") == "zone"
        and str(getattr(task, "target_id", "") or "") not in custom_task_ids
    }
    bound_zone_ids = direct_ids | blocked_ids
    for target_id in sorted(scheduled_zone_ids - bound_zone_ids):
        unresolved.append({
            "code": "approved_zone_binding_missing",
            "target_id": target_id,
            "message": "Zone execution requires an approval-bound candidate geometry task.",
        })
        task_statuses[target_id] = "failed"
    return _worker_result(
        state,
        zone_targets,
        custom_targets,
        invalid_custom_tasks,
        zone_changes,
        layers,
        unresolved,
        diagnostics,
        task_statuses,
        direct_targets,
        blocked_targets,
    )


def _worker_result(
    state: ExecuteAgentState,
    zone_targets: list[Any],
    custom_targets: list[Any],
    invalid_custom_tasks: list[Any],
    zone_changes: list[Any],
    layers: list[dict[str, Any]],
    unresolved: list[dict[str, Any]],
    diagnostics: list[dict[str, Any]],
    task_statuses: dict[str, str],
    direct_targets: list[Any] | None = None,
    blocked_targets: list[Any] | None = None,
) -> WorkerResult:
    worker_targets = (
        list(direct_targets or [])
        + list(blocked_targets or [])
        + zone_targets
        + custom_targets
        + invalid_custom_tasks
    )
    task_results = []
    for task in list(getattr(state.execution_plan, "worker_tasks", None) or []):
        worker_type = getattr(task, "worker_type", "")
        worker_type = getattr(worker_type, "value", worker_type)
        if str(worker_type) != "parcel_transformation":
            continue
        target_id = str(getattr(task, "target_id", "") or "")
        result = _task_execution_result(
            state,
            "parcel_transformation",
            target_id,
            task_id=str(getattr(task, "task_id", "") or ""),
            candidate_id=str(getattr(task, "candidate_id", "") or ""),
            status=task_statuses.get(target_id, "failed"),
            diagnostics=[
                item for item in unresolved
                if item.get("target_id") == target_id or not item.get("target_id")
            ],
        )
        if result is not None:
            task_results.append(result)
    return WorkerResult(
        worker_type="zone",
        task_results=task_results,
        layers=layers,
        parcel_changes=zone_changes,
        unresolved_items=unresolved,
        diagnostics=diagnostics,
        scenario_features=[
            item
            for layer in layers
            for item in _scenario_features_for_layer(
                state, layer, generation_operation="zone_worker"
            )
        ],
        task_id=(
            str(getattr(state.execution_plan.worker_tasks[0], "task_id", ""))
            if state.execution_plan and len(state.execution_plan.worker_tasks) == 1
            else ""
        ),
    )

__all__ = ["_zone_worker"]
