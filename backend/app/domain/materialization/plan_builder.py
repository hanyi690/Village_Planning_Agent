"""Build the authoritative, target-bound EXECUTE dispatch plan."""

from __future__ import annotations

from typing import Any

from app.contracts.artifacts.deferral_contracts import DeferralLedger
from app.contracts.workflow.execution_plan_contracts import ExecutionPlan, WorkerTask, WorkerType
from app.contracts.domain.selection_contracts import TargetAssignment


_CLASSIFICATION_OUTPUT_KINDS = frozenset({"parcel", "polygon"})
_TASK_SPECS = (
    ("project", "project_targets"),
    ("zone", "zone_targets"),
    ("zone", "custom_zone_targets"),
    ("facility", "facilities"),
    ("axis", "development_axes"),
    ("road", "road_targets"),
)


def _unwrap_intent(intent: Any) -> Any:
    return getattr(intent, "typed_intent", None) or intent


def _items(intent: Any, name: str) -> list[Any]:
    value = intent.get(name) if isinstance(intent, dict) else getattr(intent, name, None)
    return list(value or [])


def _deferred_target_ids(ledger: Any) -> set[str]:
    if not isinstance(ledger, DeferralLedger):
        return set()
    return {str(entry.target_id) for entry in (getattr(ledger, "entries", None) or [])}


def _value(target: Any, name: str, default: Any = None) -> Any:
    if isinstance(target, dict):
        return target.get(name, default)
    return getattr(target, name, default)


def _classification_status(target: Any) -> str:
    decision = _value(target, "classification_decision")
    status = _value(decision, "status") if decision is not None else "missing"
    return str(getattr(status, "value", status) or "unresolved")


def _classification_required(target: Any, assignment: Any) -> bool:
    if _value(target, "materialization_role") in {
        "functional_overlay",
        "protection_overlay",
        "restoration_overlay",
    }:
        return False
    if _value(target, "category_code") and _value(target, "vocabulary_name"):
        return True
    target_kind = str(_value(target, "expected_output_kind", "") or "")
    assignment_kind = str(_value(assignment, "expected_output_kind", "") or "")
    return bool({target_kind, assignment_kind} & _CLASSIFICATION_OUTPUT_KINDS)


def _classification_is_resolved(target: Any) -> bool:
    return _classification_status(target) == "resolved"


def _target_index(intent: Any) -> dict[str, Any]:
    return {
        str(_value(target, "target_id", "")): target
        for _, field_name in _TASK_SPECS
        for target in _items(intent, field_name)
        if str(_value(target, "target_id", "") or "")
    }


def classification_boundary_diagnostics(
    intent: Any,
    execution_plan: ExecutionPlan | None = None,
    *,
    deferral_ledger: Any = None,
) -> list[dict[str, Any]]:
    """Return auditable violations without deriving a planning class.

    This is deliberately usable by both EXECUTE_PLAN and the EXECUTE stage:
    an old persisted plan is not trusted merely because it contains a worker
    task.  Only a typed ``DeferralLedger`` can authorize an unresolved target
    to remain outside ``worker_tasks``.
    """
    intent = _unwrap_intent(intent)
    targets = _target_index(intent)
    deferred_ids = _deferred_target_ids(deferral_ledger)
    diagnostics: list[dict[str, Any]] = []

    for target_id, target in targets.items():
        assignment_kind = ""
        if execution_plan is not None:
            assignment_kind = next(
                (
                    str(_value(task, "expected_output_kind", "") or "")
                    for task in list(getattr(execution_plan, "worker_tasks", None) or [])
                    + list(getattr(execution_plan, "deferred_tasks", None) or [])
                    if str(_value(task, "target_id", "") or "") == target_id
                ),
                "",
            )
        assignment = {"expected_output_kind": assignment_kind}
        if not _classification_required(target, assignment) or _classification_is_resolved(target):
            continue
        if target_id in deferred_ids:
            continue
        diagnostics.append(
            {
                "code": "classification_decision_required",
                "target_id": target_id,
                "expected_output_kind": str(_value(target, "expected_output_kind", "") or ""),
                "classification_status": _classification_status(target),
                "message": (
                    "EXECUTE requires a resolved ClassificationDecision for parcel/polygon output; "
                    "the target was not dispatched and has no valid DeferralLedger entry."
                ),
            }
        )

    if execution_plan is not None:
        for task in list(getattr(execution_plan, "worker_tasks", None) or []):
            output_kind = str(_value(task, "expected_output_kind", "") or "")
            if output_kind not in _CLASSIFICATION_OUTPUT_KINDS:
                continue
            target_id = str(_value(task, "target_id", "") or "")
            target = targets.get(target_id)
            if target is None:
                assignment = _value(task, "assignment")
                binding = _value(assignment, "target_binding", {}) or {}
                target = binding if isinstance(binding, dict) else None
            if target is None or not _classification_is_resolved(target):
                diagnostics.append(
                    {
                        "code": "worker_task_classification_boundary_violation",
                        "target_id": target_id,
                        "expected_output_kind": output_kind,
                        "classification_status": (
                            _classification_status(target) if target is not None else "missing"
                        ),
                        "message": (
                            "A parcel/polygon worker task has no resolved explicit classification; "
                            "EXECUTE refuses to run the persisted plan."
                        ),
                    }
                )
    return diagnostics


def _worker_type(target_type: str, target: Any) -> WorkerType:
    if getattr(target, "execution_mode", "spatial") == "non_spatial":
        return WorkerType.NON_SPATIAL_ACTION
    return {
        "project": WorkerType.PROJECT_FOOTPRINT,
        "zone": WorkerType.PARCEL_TRANSFORMATION,
        "facility": WorkerType.FACILITY_PLACEMENT,
        "axis": WorkerType.AXIS_CONSTRUCTION,
        "road": WorkerType.ROAD_CONSTRUCTION,
    }[target_type]


def _has_resolution_evidence(target: Any, assignment: Any) -> bool:
    """True when a target now carries grounded placement evidence.

    A HUMAN deferral is a point-in-time decision.  When a later GROUND/SELECT
    revision resolves the spatial reference (candidate parcels, a selected
    parcel, an anchor, or explicit road endpoints), the target must be lifted
    back into ``worker_tasks`` so the worker can actually execute instead of
    being locked out forever by an earlier deferral.
    """
    if getattr(target, "road_planning_kind", None):
        if getattr(target, "road_planning_kind", None) == "existing_road_intervention":
            return bool(
                getattr(target, "existing_road_feature_ids", None)
                or getattr(target, "existing_road_segment_ids", None)
            ) and getattr(getattr(target, "routing_evidence", None), "current_network", None) is not None
        start = getattr(target, "start_endpoint", None)
        end = getattr(target, "end_endpoint", None)
        routing = getattr(target, "routing_evidence", None)
        return bool(
            getattr(start, "resolution_status", "") == "resolved"
            and getattr(end, "resolution_status", "") == "resolved"
            and getattr(routing, "has_routing_basis", False)
        )
    if getattr(target, "materialization_role", None) == "land_use_assignment":
        return bool(
            assignment is not None
            and getattr(assignment, "status", "") == "placed"
            and getattr(assignment, "selected_bsms", None)
            and getattr(assignment, "allocation_lineage_refs", None)
        )
    if assignment is not None:
        status = getattr(assignment, "status", "")
        if status in {"placed", "ready"}:
            if getattr(assignment, "selected_bsm", None):
                return True
            if getattr(assignment, "anchor_point", None):
                return True
    if getattr(target, "candidate_bsms", None):
        return True
    for field in ("path_bsms", "start_anchor", "end_anchor"):
        if getattr(target, field, None):
            return True
    return False


def build_execution_plan(
    intent,
    site_selection,
    land_design_briefs,
    *,
    run_id: str = "",
    context_version: str = "",
    deferral_ledger: Any = None,
    portfolio_decision_ref: str = "",
    global_zone_allocation_ref: str = "",
) -> ExecutionPlan:
    """Create self-contained worker tasks keyed only by stable target IDs."""
    intent = _unwrap_intent(intent)
    assignments = {
        item.target_id: item for item in (getattr(site_selection, "target_assignments", None) or [])
    }
    deferred_ids = _deferred_target_ids(deferral_ledger)
    tasks: list[WorkerTask] = []
    deferred_tasks: list[WorkerTask] = []
    project_task_ids: list[str] = []
    facility_task_ids: list[str] = []
    for target_type, field_name in _TASK_SPECS:
        for target in _items(intent, field_name):
            target_id = str(getattr(target, "target_id", "") or "")
            if not target_id:
                continue
            assignment = assignments.get(target_id)
            if assignment is None:
                assignment = TargetAssignment(
                    target_id=target_id,
                    target_type=target_type,
                    status="unplaced",
                    expected_output_kind=getattr(target, "expected_output_kind", "parcel"),
                    target_binding=target.model_dump(mode="json"),
                    reason="site_selection_assignment_missing",
                )
            elif not assignment.target_binding:
                assignment = assignment.model_copy(update={"target_binding": target.model_dump(mode="json")})
            worker_type = _worker_type(target_type, target)
            task_id = f"{worker_type.value}:{target_id}"
            depends_on = []
            if target_type == "zone":
                depends_on = list(project_task_ids)
            elif target_type == "road":
                depends_on = list(project_task_ids) + list(facility_task_ids)
            task = WorkerTask(
                task_id=task_id,
                worker_type=worker_type,
                target_id=target_id,
                target_type=target_type,
                expected_output_kind=assignment.expected_output_kind,
                assignment=assignment,
                payload={"target_id": target_id},
                depends_on=depends_on,
                input_artifact_refs=[
                    "artifact:target_projection",
                    (
                        f"artifact:portfolio_decision:{portfolio_decision_ref}"
                        if portfolio_decision_ref
                        else "artifact:portfolio_decision"
                    ),
                    *(
                        [f"artifact:global_zone_allocation:{global_zone_allocation_ref}"]
                        if target_type == "zone" and global_zone_allocation_ref
                        else []
                    ),
                ],
            )
            if assignment.status in {"unplaced", "deferred"}:
                deferred_tasks.append(
                    task.model_copy(
                        update={
                            "assignment": assignment.model_copy(update={"status": "deferred"})
                        }
                    )
                )
                continue
            if _classification_required(target, assignment) and not _classification_is_resolved(target):
                if target_id in deferred_ids:
                    deferred_tasks.append(task)
                continue
            if target_id in deferred_ids:
                # Re-execute a previously deferred target only when this
                # revision actually resolves its placement; otherwise the
                # deferral stays (and VALIDATE must not re-flag it).
                if not _has_resolution_evidence(target, assignment):
                    deferred_tasks.append(task)
                    continue
            tasks.append(task)
            if target_type == "project":
                project_task_ids.append(task_id)
            elif target_type == "facility":
                facility_task_ids.append(task_id)
    return ExecutionPlan(
        schema_version="2.0",
        plan_id=f"execute-{run_id or 'current'}",
        worker_tasks=tasks,
        deferred_tasks=deferred_tasks,
        dependencies=[{"from": dependency, "to": task.task_id} for task in tasks for dependency in task.depends_on],
        context_version=context_version,
        land_design_briefs=list(land_design_briefs or []),
        portfolio_decision_ref=portfolio_decision_ref,
    )


def defer_plan_tasks(
    plan: ExecutionPlan,
    target_ids: list[str],
    review_id: str = "",
) -> ExecutionPlan:
    """Create an ExecutionPlan revision that moves targets to deferred_tasks.

    Deferred targets leave ``worker_tasks``, their assignments are stamped
    ``deferred``, and the revision id carries the human review reference.
    Pure construction — the caller owns CAS writes.
    """
    deferred_set = set(target_ids)
    kept_tasks: list[WorkerTask] = []
    moved_tasks: list[WorkerTask] = []
    for task in plan.worker_tasks:
        if task.target_id not in deferred_set:
            kept_tasks.append(task)
            continue
        assignment = task.assignment.model_copy(update={"status": "deferred"})
        moved_tasks.append(task.model_copy(update={"assignment": assignment}))
    return plan.model_copy(deep=True, update={
        "plan_id": f"{plan.plan_id}:review-{review_id[:12]}",
        "worker_tasks": kept_tasks,
        "deferred_tasks": list(plan.deferred_tasks) + moved_tasks,
    })


__all__ = [
    "build_execution_plan",
    "classification_boundary_diagnostics",
    "defer_plan_tasks",
]
