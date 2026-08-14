"""Zone worker: materialize audited global assignments and independent overlays."""

from __future__ import annotations

from typing import Any, Dict, List

from app.contracts.spatial.global_zone_allocation_contracts import (
    AuthoritativeZoneParcelAssignment,
    GlobalZoneAllocationResult,
    ZoneOverlayTargetRef,
)
from app.contracts.spatial.parcel_change_contracts import ParcelChange
from app.contracts.workflow.execution_plan_contracts import WorkerResult
from app.domain.materialization.execute_state import ExecuteAgentState
from app.domain.materialization.nodes.common import _execution_error
from app.domain.materialization.nodes.worker_common import (
    _execution_intent_from_plan,
    _intent_list,
    _resolve_parcel_by_bsm,
    _task_enabled,
    _task_execution_result,
)
from app.infrastructure.logging import get_logger

logger = get_logger(__name__)


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


def _allocation_result_adapter(
    state: ExecuteAgentState,
    explicit: GlobalZoneAllocationResult | dict | None,
) -> tuple[GlobalZoneAllocationResult | None, dict[str, Any] | None]:
    """Read the typed artifact from an explicit dependency boundary.

    ExecuteAgentState intentionally has no allocation-artifact slot yet.  The
    canonical worker wrapper supplies ``explicit`` from deps; direct graph use
    may inject it through ``state.ports.global_zone_allocation_result``.  No
    execution-plan or parcel-pool fallback is allowed.
    """
    raw: Any = explicit
    if raw is None:
        raw = getattr(state, "global_zone_allocation_result", None)
    if raw is None:
        ports = getattr(state, "ports", None)
        raw = (
            getattr(ports, "global_zone_allocation_result", None)
            if ports is not None
            else None
        )
    if raw is None:
        return None, {
            "code": "global_zone_allocation_missing",
            "message": (
                "Zone materialization requires an explicit "
                "GlobalZoneAllocationResult artifact."
            ),
        }
    if isinstance(raw, GlobalZoneAllocationResult):
        return raw, None
    try:
        return GlobalZoneAllocationResult.model_validate(raw), None
    except (TypeError, ValueError) as exc:
        return None, {
            "code": "global_zone_allocation_invalid",
            "message": "Global zone allocation artifact failed contract validation.",
            "exception_type": type(exc).__name__,
        }


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


def _authoritative_assignment_layer(
    assignments: list[AuthoritativeZoneParcelAssignment],
    parcel_by_bsm: Dict[str, Any],
) -> dict | None:
    features: list[dict[str, Any]] = []
    for assignment in sorted(assignments, key=lambda item: (item.target_id, item.bsm)):
        geometry = _parcel_geometry(parcel_by_bsm.get(assignment.bsm))
        if not geometry:
            continue
        lineage = assignment.lineage
        features.append({
            "type": "Feature",
            "properties": {
                "bsm": assignment.bsm,
                "target_id": assignment.target_id,
                "zone_id": assignment.zone_id,
                "project_ref": assignment.target_id,
                "lineage_id": lineage.lineage_id,
                "claim_refs": list(lineage.claim_refs),
                "source_instruction_id": lineage.source_instruction_id,
                "source_report_key": lineage.source_report_key,
                "classification_system": assignment.classification_system,
                "classification_code": assignment.classification_code,
                "planning_land_use": assignment.land_use,
                "geometry_ref": lineage.geometry_ref,
                "materialization_role": assignment.materialization_role,
                "area_ha": assignment.area_ha,
                "candidate_provenance_refs": list(
                    lineage.candidate_provenance_refs
                ),
                "parcel_provenance_refs": list(lineage.parcel_provenance_refs),
            },
            "geometry": geometry,
        })
    if not features:
        return None
    return {
        "layerType": "authoritative_zone_assignment",
        "layerName": "权威规划地类",
        "data": {"type": "FeatureCollection", "features": features},
    }


def _overlay_layers(
    overlays: list[ZoneOverlayTargetRef],
    parcel_by_bsm: Dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    features_by_role: dict[str, list[dict[str, Any]]] = {}
    unresolved: list[dict[str, Any]] = []
    for overlay in sorted(overlays, key=lambda item: item.target_id):
        for bsm in sorted(set(overlay.candidate_bsms)):
            geometry = _parcel_geometry(parcel_by_bsm.get(bsm))
            if not geometry:
                unresolved.append({
                    "code": "overlay_parcel_missing",
                    "target_id": overlay.target_id,
                    "bsm": bsm,
                    "materialization_role": overlay.materialization_role,
                })
                continue
            features_by_role.setdefault(overlay.materialization_role, []).append({
                "type": "Feature",
                "properties": {
                    "target_id": overlay.target_id,
                    "project_ref": overlay.target_id,
                    "bsm": bsm,
                    "materialization_role": overlay.materialization_role,
                    "provenance_refs": list(overlay.provenance_refs),
                },
                "geometry": geometry,
            })
    layers = [
        {
            "layerType": role,
            "layerName": role,
            "data": {"type": "FeatureCollection", "features": features},
        }
        for role, features in sorted(features_by_role.items())
    ]
    return layers, unresolved


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


def _blocking_assignment_diagnostics(
    allocation: GlobalZoneAllocationResult,
    scheduled_target_ids: set[str],
    parcel_by_bsm: Dict[str, Any],
) -> list[dict[str, Any]]:
    diagnostics: list[dict[str, Any]] = []
    by_bsm: dict[str, list[str]] = {}
    for assignment in allocation.assignments:
        by_bsm.setdefault(assignment.bsm, []).append(assignment.target_id)
        if assignment.target_id not in scheduled_target_ids:
            diagnostics.append({
                "code": "assignment_target_not_scheduled",
                "target_id": assignment.target_id,
                "bsm": assignment.bsm,
            })
        if assignment.bsm not in parcel_by_bsm:
            diagnostics.append({
                "code": "assignment_parcel_missing",
                "target_id": assignment.target_id,
                "bsm": assignment.bsm,
            })
    for bsm, target_ids in sorted(by_bsm.items()):
        if len(target_ids) > 1:
            diagnostics.append({
                "code": "authoritative_assignment_duplicate_bsm",
                "bsm": bsm,
                "target_ids": sorted(target_ids),
            })
    return diagnostics


def _zone_worker(
    state: ExecuteAgentState,
    *,
    allocation_result: GlobalZoneAllocationResult | dict | None = None,
) -> WorkerResult:
    """Materialize only authoritative assignments; overlays remain non-exclusive."""
    from app.domain.materialization.land_design_worker import design_zone_parcel

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
    parcel_by_bsm = _resolve_parcel_by_bsm(state)
    diagnostics: List[Dict[str, Any]] = []
    unresolved: List[Dict[str, Any]] = []
    task_statuses: Dict[str, str] = {}
    layers: list[dict[str, Any]] = []

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

    allocation, adapter_error = _allocation_result_adapter(state, allocation_result)
    if zone_targets and adapter_error is not None:
        unresolved.append(adapter_error)
        for target in zone_targets:
            task_statuses[str(target.target_id)] = "failed"
        return _worker_result(
            state,
            zone_targets,
            custom_targets,
            invalid_custom_tasks,
            [],
            layers,
            unresolved,
            diagnostics,
            task_statuses,
        )

    zone_changes: list[ParcelChange] = []
    if allocation is not None:
        overlay_layers, overlay_unresolved = _overlay_layers(
            list(allocation.overlay_targets),
            parcel_by_bsm,
        )
        layers.extend(overlay_layers)
        unresolved.extend(overlay_unresolved)
        if allocation.status not in {"OPTIMAL", "PARTIAL"} or not allocation.feasible:
            unresolved.append({
                "code": "global_zone_allocation_not_materializable",
                "status": allocation.status,
            })
            for target in zone_targets:
                task_statuses[str(target.target_id)] = "failed"
        else:
            scheduled_ids = {str(target.target_id) for target in zone_targets}
            blockers = _blocking_assignment_diagnostics(
                allocation,
                scheduled_ids,
                parcel_by_bsm,
            )
            if blockers:
                unresolved.extend(blockers)
                for target_id in scheduled_ids:
                    task_statuses[target_id] = "failed"
            else:
                repair_skip_by_target = {
                    target_id: _repair_skip_bsms(state, target_id)
                    for target_id in scheduled_ids
                }
                materialized_assignments: list[AuthoritativeZoneParcelAssignment] = []
                skipped_repair_assignments: list[AuthoritativeZoneParcelAssignment] = []
                for assignment in sorted(
                    allocation.assignments,
                    key=lambda item: (item.target_id, item.bsm),
                ):
                    if assignment.bsm in repair_skip_by_target.get(
                        assignment.target_id, set()
                    ):
                        skipped_repair_assignments.append(assignment)
                        continue
                    materialized_assignments.append(assignment)
                for assignment in skipped_repair_assignments:
                    unresolved.append({
                        "code": "assignment_skipped_by_repair",
                        "target_id": assignment.target_id,
                        "bsm": assignment.bsm,
                        "lineage_id": assignment.lineage.lineage_id,
                        "message": (
                            "Assignment was not materialized because a VALIDATE "
                            "repair directive marks this BSM as offending."
                        ),
                    })
                assignment_target_ids = {
                    assignment.target_id for assignment in materialized_assignments
                }
                missing_target_ids = sorted(scheduled_ids - assignment_target_ids)
                for target_id in missing_target_ids:
                    unresolved.append({
                        "code": "authoritative_assignment_missing",
                        "target_id": target_id,
                    })
                    task_statuses[target_id] = "failed"

                pending_changes: list[ParcelChange] = []
                failed_assignments: list[dict[str, Any]] = []
                for assignment in sorted(
                    materialized_assignments,
                    key=lambda item: (item.target_id, item.bsm),
                ):
                    changes = design_zone_parcel(assignment, parcel_by_bsm)
                    if len(changes) != 1:
                        failed_assignments.append({
                            "code": "assignment_materialization_failed",
                            "target_id": assignment.target_id,
                            "bsm": assignment.bsm,
                            "lineage_id": assignment.lineage.lineage_id,
                        })
                        continue
                    pending_changes.extend(changes)
                if failed_assignments:
                    unresolved.extend(failed_assignments)
                    for target_id in scheduled_ids:
                        task_statuses[target_id] = "failed"
                else:
                    zone_changes = pending_changes
                    for target_id in assignment_target_ids:
                        task_statuses[target_id] = "succeeded"
                    assignment_layer = _authoritative_assignment_layer(
                        list(materialized_assignments),
                        parcel_by_bsm,
                    )
                    if assignment_layer is not None:
                        layers.insert(0, assignment_layer)

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
    )


def _worker_result(
    state: ExecuteAgentState,
    zone_targets: list[Any],
    custom_targets: list[Any],
    invalid_custom_tasks: list[Any],
    zone_changes: list[ParcelChange],
    layers: list[dict[str, Any]],
    unresolved: list[dict[str, Any]],
    diagnostics: list[dict[str, Any]],
    task_statuses: dict[str, str],
) -> WorkerResult:
    worker_targets = zone_targets + custom_targets + invalid_custom_tasks
    return WorkerResult(
        worker_type="zone",
        task_results=[
            result
            for target in worker_targets
            if (result := _task_execution_result(
                state,
                "parcel_transformation",
                str(getattr(target, "target_id", "") or ""),
                status=task_statuses.get(
                    str(getattr(target, "target_id", "") or ""),
                    "failed",
                ),
                diagnostics=[
                    item
                    for item in unresolved
                    if item.get("target_id")
                    == str(getattr(target, "target_id", "") or "")
                    or not item.get("target_id")
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
    blocking_codes = {
        "global_zone_allocation_missing",
        "global_zone_allocation_invalid",
        "authoritative_assignment_duplicate_bsm",
        "assignment_parcel_missing",
        "assignment_materialization_failed",
    }
    blocker = next(
        (
            item
            for item in result.unresolved_items
            if item.get("code") in blocking_codes
        ),
        None,
    )
    if blocker is not None:
        update["execution_errors"] = _execution_error(
            state,
            "layout",
            str(blocker.get("code")),
            str(blocker.get("message") or "Zone materialization is blocked."),
        )["execution_errors"]
    if result.parcel_changes or result.layers:
        update["allocation_summary"] = {
            "mode": "global_authoritative_assignment",
            "allocated_count": len(result.parcel_changes),
            "overlay_feature_count": sum(
                len((layer.get("data") or {}).get("features") or [])
                for layer in result.layers
                if str(layer.get("layerType") or "").endswith("overlay")
            ),
            "adjustments_applied": len(list(state.constraint_adjustments or [])),
        }
    return update


__all__ = [
    "_allocation_result_adapter",
    "_zone_worker",
    "_zone_worker_node",
]
