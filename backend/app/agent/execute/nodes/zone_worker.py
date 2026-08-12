"""Zone worker node: deterministic zone reclassification + MIP allocation."""

from __future__ import annotations

from typing import Any, Dict, List

from app.agent.execute.execute_state import ExecuteAgentState
from app.agent.execute.nodes.common import _execution_error
from app.agent.execute.nodes.worker_common import (
    _execution_intent_from_plan,
    _intent_list,
    _resolve_parcel_by_bsm,
    _task_enabled,
    _task_execution_result,
)
from app.modules.schema.contracts.execution_plan_contracts import WorkerResult
from app.modules.schema.contracts.parcel_change_contracts import ParcelChange
from app.utils.logger import get_logger

logger = get_logger(__name__)


def _function_zone_layer(zone_changes: list[ParcelChange]) -> dict | None:
    """Build the diagnostic function-zone overlay from typed changes."""
    from shapely import wkt
    from shapely.geometry import mapping

    features = []
    for change in zone_changes:
        if getattr(change, "action", "") != "reclassify":
            continue
        after_wkt = getattr(change, "after_geometry_wkt", "") or ""
        if not after_wkt:
            continue
        try:
            geometry = wkt.loads(after_wkt)
        except Exception:
            continue
        if geometry.is_empty:
            continue
        classification = getattr(change, "after_classification", None)
        bsm = str(getattr(change, "bsm", ""))
        features.append({
            "type": "Feature",
            "properties": {
                "bsm": bsm,
                "planning_land_use": str(getattr(classification, "code", "") or ""),
                "zone_type": str(getattr(classification, "canonical_name", "") or ""),
                "action": getattr(change, "action", ""),
                "source_bsm": bsm,
                "area_ha": round(float(getattr(change, "new_area_ha", 0) or 0), 2),
            },
            "geometry": mapping(geometry),
        })
    if not features:
        return None
    return {
        "layerType": "function_zone",
        "layerName": "功能分区",
        "data": {"type": "FeatureCollection", "features": features},
    }


def _resolve_zone_allocator(state: ExecuteAgentState) -> Any:
    """ZoneAllocatorPort from injected ports, else the default PuLP adapter."""
    ports = getattr(state, "ports", None)
    allocator = getattr(ports, "zone_allocator", None) if ports is not None else None
    if allocator is None:
        from app.modules.spatial_ops.allocation.zone_allocator_adapter import PuLPZoneAllocator

        allocator = PuLPZoneAllocator()
    return allocator


def _zone_target_key(zone_target: Any) -> str:
    return str(
        getattr(zone_target, "zone_id", None)
        or getattr(zone_target, "land_use", None)
        or ""
    )


def _custom_zone_targets_from_plan(state: ExecuteAgentState) -> List[Any]:
    """Restore custom targets from existing zone-task bindings."""
    from app.modules.schema.contracts.custom_zone_contracts import CustomZoneTarget

    targets: List[Any] = []
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
        except ValueError:
            continue
    return targets


def _allocate_empty_zone_targets(
    state: ExecuteAgentState,
    empty_targets: List[Any],
    parcel_by_bsm: Dict[str, Any],
    zone_changes: List[ParcelChange],
    diagnostics: List[Dict[str, Any]],
    task_statuses: Dict[str, str],
) -> List[Dict[str, Any]]:
    """MIP-allocate parcels for zone targets with no candidate_bsms.

    The unclaimed parcel pool (parcels not claimed by any non-empty zone target)
    is passed as the candidate set. Infeasible allocations are surfaced as
    ``design_unresolved`` diagnostics - never silently skipped.
    """
    unresolved: List[Dict[str, Any]] = []
    if not empty_targets:
        return unresolved

    claimed: set = set()
    for zone_target in _intent_list(_execution_intent_from_plan(state), "zone_targets"):
        for bsm in getattr(zone_target, "candidate_bsms", None) or []:
            claimed.add(str(bsm))
    pool = [bsm for bsm in parcel_by_bsm if str(bsm) not in claimed]

    targets: Dict[str, float] = {}
    candidates: Dict[str, List[str]] = {}
    metadata: Dict[str, Any] = {"parcel_by_bsm": parcel_by_bsm}
    for zone_target in empty_targets:
        key = _zone_target_key(zone_target)
        if not key:
            continue
        targets[key] = float(getattr(zone_target, "area_ha", None) or 0.0)
        candidates[key] = list(pool)
        metadata[key] = {"land_use": getattr(zone_target, "land_use", "") or ""}

    if not targets:
        return unresolved

    allocator = _resolve_zone_allocator(state)
    try:
        solution = allocator.allocate(targets, candidates, constraints=None, metadata=metadata)
    except Exception as e:  # pragma: no cover - defensive
        for zone_target in empty_targets:
            target_id = str(getattr(zone_target, "target_id", "") or "")
            task_statuses[target_id] = "failed"
            unresolved.append({
                "code": "design_unresolved",
                "kind": "zone_allocation_error",
                "target": _zone_target_key(zone_target),
                "target_id": target_id,
                "message": str(e),
            })
        return unresolved

    if not getattr(solution, "feasible", False):
        for zone_target in empty_targets:
            target_id = str(getattr(zone_target, "target_id", "") or "")
            task_statuses[target_id] = "failed"
            unresolved.append({
                "code": "design_unresolved",
                "kind": "zone_allocation_infeasible",
                "target": _zone_target_key(zone_target),
                "target_id": target_id,
                "diagnostics": list(getattr(solution, "diagnostics", None) or []),
            })
        return unresolved

    from app.agent.execute.land_design_worker import design_zone_parcel

    for zone_target in empty_targets:
        target_id = str(getattr(zone_target, "target_id", "") or "")
        key = _zone_target_key(zone_target)
        assigned_bsms = [
            entry.bsm
            for entry in getattr(solution, "assignments", None) or []
            if entry.zone_id == key
        ]
        if not assigned_bsms:
            task_statuses[target_id] = "failed"
            unresolved.append({
                "code": "design_unresolved",
                "kind": "zone_allocation_empty",
                "target": key,
                "target_id": target_id,
                "message": "Allocator returned no assignments for zone.",
            })
            continue
        allocated_target = zone_target.model_copy(update={"candidate_bsms": assigned_bsms})
        changes = design_zone_parcel(allocated_target, parcel_by_bsm)
        zone_changes.extend(changes)
        task_statuses[target_id] = "succeeded" if changes else "failed"
        diagnostics.append({
            "code": "zone_allocated",
            "target": key,
            "assigned": len(assigned_bsms),
        })
    return unresolved


def _zone_worker(state: ExecuteAgentState) -> WorkerResult:
    """Zone worker: deterministic zone reclassification + MIP allocation.

    Reclassifies each zone target's candidate parcels to the zone's planning
    land use via the Land Design Worker. Zone targets with empty
    ``candidate_bsms`` are solved through the ``ZoneAllocatorPort`` (PuLP MIP);
    infeasible allocations become ``design_unresolved`` diagnostics.
    """
    from app.agent.execute.land_design_worker import design_zone_parcel

    if not _task_enabled(state, "layout"):
        return WorkerResult(worker_type="zone")

    custom_targets = _custom_zone_targets_from_plan(state)
    custom_target_ids = {str(target.target_id) for target in custom_targets}
    if custom_target_ids:
        plan = state.execution_plan.model_copy(update={
            "worker_tasks": [
                task
                for task in state.execution_plan.worker_tasks
                if str(getattr(task, "target_id", "") or "") not in custom_target_ids
            ]
        })
        zone_state = state.model_copy(update={"execution_plan": plan})
        bound_intent = _execution_intent_from_plan(zone_state)
    else:
        zone_state = state
        bound_intent = _execution_intent_from_plan(state)
    zone_targets = _intent_list(bound_intent, "zone_targets")
    zone_targets = [
        target for target in zone_targets
        if str(getattr(target, "target_id", "") or "") not in custom_target_ids
    ]
    parcel_by_bsm = _resolve_parcel_by_bsm(state)

    diagnostics: List[Dict[str, Any]] = []
    unresolved: List[Dict[str, Any]] = []

    if not zone_targets and not custom_targets:
        message = "No explicit planning zone targets were derived from the reports."
        logger.error("[EXECUTE:zone] %s", message)
        unresolved.append({"code": "missing_zone_targets", "message": message})
        return WorkerResult(
            worker_type="zone", unresolved_items=unresolved, diagnostics=diagnostics
        )

    zone_changes: List[ParcelChange] = []
    task_statuses: Dict[str, str] = {}
    empty_targets = []
    for zone_target in zone_targets:
        decision = getattr(zone_target, "classification_decision", None)
        if decision is None or getattr(decision, "status", "") != "resolved":
            target_id = str(getattr(zone_target, "target_id", "") or "")
            task_statuses[target_id] = "failed"
            unresolved.append({
                "code": "classification_unresolved",
                "target_id": target_id,
                "message": "Zone execution requires an explicit resolved classification decision.",
            })
            continue
        if not getattr(zone_target, "candidate_bsms", None):
            empty_targets.append(zone_target)
            continue
        changes = design_zone_parcel(zone_target, parcel_by_bsm)
        zone_changes.extend(changes)
        task_statuses[str(getattr(zone_target, "target_id", "") or "")] = (
            "succeeded" if changes else "failed"
        )
        if not changes:
            unresolved.append({
                "code": "zone_output_empty",
                "target_id": getattr(zone_target, "target_id", ""),
                "message": "Zone target produced no parcel changes.",
            })

    unresolved.extend(
        _allocate_empty_zone_targets(
            zone_state,
            empty_targets,
            parcel_by_bsm,
            zone_changes,
            diagnostics,
            task_statuses,
        )
    )

    if custom_targets:
        from app.modules.spatial_ops.zoning.custom_zone_changeset import (
            materialize_custom_zone_changes,
        )

        three_lines = state.kg_three_lines if isinstance(state.kg_three_lines, dict) else None
        for target in custom_targets:
            materialized = materialize_custom_zone_changes(
                target,
                parcel_by_bsm,
                three_lines=three_lines,
            )
            zone_changes.extend(materialized.changes)
            unresolved.extend(materialized.unresolved_items)
            diagnostics.extend(materialized.diagnostics)
            task_statuses[target.target_id] = (
                "succeeded" if materialized.changes and not materialized.unresolved_items else "failed"
            )

    layers = []
    func_layer = _function_zone_layer(zone_changes)
    if func_layer:
        layers.append(func_layer)

    return WorkerResult(
        worker_type="zone",
        task_results=[
            result
            for zone_target in zone_targets + custom_targets
            if (result := _task_execution_result(
                state,
                "parcel_transformation",
                zone_target.target_id,
                status=task_statuses.get(zone_target.target_id, "failed"),
                diagnostics=[
                    item for item in unresolved
                    if item.get("target_id") == zone_target.target_id
                ],
            )) is not None
        ],
        layers=layers,
        parcel_changes=zone_changes,
        unresolved_items=unresolved,
        diagnostics=diagnostics,
    )


async def _zone_worker_node(state: ExecuteAgentState) -> dict:
    if not _task_enabled(state, "layout"):
        return {}
    result = _zone_worker(state)
    update: Dict[str, Any] = {"worker_results": [result]}
    if any(item.get("code") == "missing_zone_targets" for item in result.unresolved_items):
        update["execution_errors"] = _execution_error(
            state, "layout", "missing_zone_targets",
            "No explicit planning zone targets were derived from the reports.",
        )["execution_errors"]
    if result.parcel_changes:
        zone_changes = list(result.parcel_changes)
        update["allocation_summary"] = {
            "mode": "deterministic",
            "allocated_count": len(zone_changes),
            "zone_target_count": sum(
                1
                for task in list(getattr(state.execution_plan, "worker_tasks", None) or [])
                if str(getattr(task, "target_type", "") or "") == "zone"
                and str(getattr(task.assignment, "target_binding", {}).get("category_code", "") or "")
                == ""
            ),
            "adjustments_applied": len(list(state.constraint_adjustments or [])),
            "custom_zone_count": sum(
                1
                for change in zone_changes
                if str(getattr(change, "intervention_id", "") or "")
                in {str(target.target_id) for target in _custom_zone_targets_from_plan(state)}
            ),
        }
    return update
