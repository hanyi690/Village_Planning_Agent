"""Build the authoritative, target-bound EXECUTE dispatch plan."""

from __future__ import annotations

from typing import Any

from app.contracts.artifacts.deferral_contracts import DeferralLedger
from app.contracts.workflow.execution_plan_contracts import ExecutionPlan, WorkerTask, WorkerType
from app.contracts.domain.selection_contracts import TargetAssignment


_CLASSIFICATION_OUTPUT_KINDS = frozenset({"parcel", "polygon"})
_TASK_SPECS = (
    ("site_area", "site_area_targets"),
    ("zone", "zone_targets"),
    ("zone", "custom_zone_targets"),
    ("facility", "facilities"),
    ("axis", "development_axes"),
    ("road", "road_targets"),
    ("linear", "linear_targets"),
)


def _unwrap_intent(intent: Any) -> Any:
    return getattr(intent, "typed_intent", None) or intent


def _items(intent: Any, name: str) -> list[Any]:
    value = intent.get(name) if isinstance(intent, dict) else getattr(intent, name, None)
    if not value and name == "site_area_targets":
        # v1 callers exposed project targets under ``project_targets``;
        # canonical v2 storage remains site_area_targets.
        value = intent.get("project_targets") if isinstance(intent, dict) else getattr(intent, "project_targets", None)
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
    materialization_role = _value(target, "materialization_role")
    if not materialization_role:
        materialization_role = _value(assignment, "materialization_role")
    if not materialization_role:
        binding = _value(assignment, "target_binding", {}) or {}
        materialization_role = _value(binding, "materialization_role")
    if materialization_role in {
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
        assignment = None
        if execution_plan is not None:
            assignment = next(
                (
                    _value(task, "assignment")
                    for task in list(getattr(execution_plan, "worker_tasks", None) or [])
                    + list(getattr(execution_plan, "deferred_tasks", None) or [])
                    if str(_value(task, "target_id", "") or "") == target_id
                ),
                "",
            )
        if assignment is None:
            assignment = {"expected_output_kind": _value(target, "expected_output_kind", "")}
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
            if target is None:
                requires_classification = True
            else:
                requires_classification = _classification_required(target, task.assignment)
            if requires_classification and (
                target is None or not _classification_is_resolved(target)
            ):
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
    if target_type == "linear":
        return WorkerType.UTILITY_NETWORK
    if target_type == "road" and str(_value(target, "asset_kind", "road")) != "road":
        return WorkerType.UTILITY_NETWORK
    return {
        "site_area": WorkerType.SITE_AREA_FOOTPRINT,
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


def _relation_dependencies(planning_graph: Any) -> dict[str, list[str]]:
    """Compile only explicit ``precedes`` relations into execution edges."""

    relations = getattr(planning_graph, "relations", None)
    if relations is None and isinstance(planning_graph, dict):
        relations = planning_graph.get("relations", [])
    dependencies: dict[str, list[str]] = {}
    for relation in list(relations or []):
        if isinstance(relation, dict):
            get = relation.get
        else:
            get = lambda key, default=None: getattr(relation, key, default)
        if str(get("relation_template", "") or "") != "precedes":
            continue
        subject = str(get("subject_ref", "") or "")
        object_ref = str(get("object_ref", "") or "")
        if not subject or not object_ref or subject == object_ref:
            continue
        dependencies.setdefault(object_ref, []).append(subject)
    return {
        target_id: list(dict.fromkeys(subjects))
        for target_id, subjects in dependencies.items()
    }


def _relation_ids_by_target(planning_graph: Any) -> dict[str, list[str]]:
    """Return all declared relation ids touching each execution target."""
    relations = getattr(planning_graph, "relations", None)
    if relations is None and isinstance(planning_graph, dict):
        relations = planning_graph.get("relations", [])
    result: dict[str, list[str]] = {}
    for relation in list(relations or []):
        get = relation.get if isinstance(relation, dict) else lambda key, default=None: getattr(relation, key, default)
        relation_id = str(get("relation_id", "") or "")
        if not relation_id:
            continue
        for target_id in (
            str(get("subject_ref", "") or ""),
            str(get("object_ref", "") or ""),
        ):
            if target_id:
                result.setdefault(target_id, []).append(relation_id)
    return {key: list(dict.fromkeys(value)) for key, value in result.items()}


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
    scenario_selected_candidate_ids: dict[str, str] | None = None,
) -> ExecutionPlan:
    """Create self-contained worker tasks keyed only by stable target IDs."""
    planning_graph = getattr(intent, "intent_graph", None)
    intent = _unwrap_intent(intent)
    scenario_id = str(getattr(site_selection, "scenario_id", "") or "")
    assignments = {
        item.target_id: item for item in (getattr(site_selection, "target_assignments", None) or [])
    }
    deferred_ids = _deferred_target_ids(deferral_ledger)
    scenario_selected_candidate_ids = {
        str(target_id): str(candidate_id)
        for target_id, candidate_id in (scenario_selected_candidate_ids or {}).items()
        if str(target_id).strip() and str(candidate_id).strip()
    }
    tasks: list[WorkerTask] = []
    deferred_tasks: list[WorkerTask] = []
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
            selected_candidate_id = scenario_selected_candidate_ids.get(target_id)
            if selected_candidate_id:
                binding = dict(assignment.target_binding or {})
                binding["candidate_id"] = selected_candidate_id
                binding["scenario_id"] = scenario_id
                assignment = assignment.model_copy(update={
                    "status": "placed",
                    "reason": "",
                    "target_binding": binding,
                })
            worker_type = _worker_type(target_type, target)
            asset_kind = str(_value(target, "asset_kind", "none") or "none")
            required_capability = (
                f"linear.{asset_kind}"
                if target_type == "linear"
                else (
                    f"linear.{asset_kind}"
                    if target_type == "road" and asset_kind != "road"
                    else worker_type.value
                )
            )
            task_id = f"{worker_type.value}:{target_id}"
            task = WorkerTask(
                task_id=task_id,
                worker_type=worker_type,
                target_id=target_id,
                target_type=target_type,
                expected_output_kind=assignment.expected_output_kind,
                assignment=assignment,
                payload={"target_id": target_id},
                depends_on=[],
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
                required_capability=required_capability,
                scenario_id=scenario_id,
                candidate_id=str(
                    _value(assignment, "target_binding", {}).get("candidate_id")
                    if isinstance(_value(assignment, "target_binding", {}), dict)
                    else ""
                ) or str(_value(assignment, "selected_bsm", "") or ""),
                relation_ids=[],
                target_binding=dict(_value(assignment, "target_binding", {}) or {}),
                defer_reason=(
                    "unsupported_capability"
                    if worker_type == WorkerType.UTILITY_NETWORK
                    else ""
                ),
            )
            if worker_type == WorkerType.UTILITY_NETWORK:
                deferred_tasks.append(
                    task.model_copy(
                        update={
                            "assignment": assignment.model_copy(update={"status": "deferred"}),
                        }
                    )
                )
                continue
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
    task_id_by_target = {
        task.target_id: task.task_id
        for task in [*tasks, *deferred_tasks]
    }
    relation_dependencies = _relation_dependencies(planning_graph)
    relation_ids_by_target = _relation_ids_by_target(planning_graph)
    if scenario_id or relation_ids_by_target:
        def _with_execution_metadata(task: WorkerTask) -> WorkerTask:
            assignment = task.assignment
            binding = dict(assignment.target_binding or {})
            candidate_id = str(
                binding.get("candidate_id")
                or _value(assignment, "selected_bsm", "")
                or ""
            )
            return task.model_copy(update={
                "scenario_id": scenario_id,
                "candidate_id": candidate_id,
                "relation_ids": relation_ids_by_target.get(task.target_id, []),
                "target_binding": binding,
            })

        tasks = [_with_execution_metadata(task) for task in tasks]
        deferred_tasks = [_with_execution_metadata(task) for task in deferred_tasks]
    if relation_dependencies:
        def _with_relation_dependencies(task: WorkerTask) -> WorkerTask:
            depends_on = [
                task_id_by_target[subject]
                for subject in relation_dependencies.get(task.target_id, [])
                if subject in task_id_by_target and task_id_by_target[subject] != task.task_id
            ]
            return task.model_copy(update={"depends_on": list(dict.fromkeys(depends_on))})

        tasks = [_with_relation_dependencies(task) for task in tasks]
        deferred_tasks = [_with_relation_dependencies(task) for task in deferred_tasks]
    return ExecutionPlan(
        schema_version="2.0",
        plan_id=f"execute-{run_id or 'current'}",
        worker_tasks=tasks,
        deferred_tasks=deferred_tasks,
        dependencies=[
            {"from": dependency, "to": task.task_id}
            for task in [*tasks, *deferred_tasks]
            for dependency in task.depends_on
        ],
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
