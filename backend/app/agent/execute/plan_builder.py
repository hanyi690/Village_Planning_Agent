"""Build the authoritative, target-bound EXECUTE dispatch plan."""

from __future__ import annotations

from typing import Any

from app.modules.schema.contracts.execution_plan_contracts import ExecutionPlan, WorkerTask, WorkerType
from app.modules.schema.contracts.selection_contracts import TargetAssignment


def _unwrap_intent(intent: Any) -> Any:
    return getattr(intent, "typed_intent", None) or intent


def _items(intent: Any, name: str) -> list[Any]:
    value = intent.get(name) if isinstance(intent, dict) else getattr(intent, name, None)
    return list(value or [])


def _deferred_target_ids(ledger: Any) -> set[str]:
    return {str(entry.target_id) for entry in (getattr(ledger, "entries", None) or [])}


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


def build_execution_plan(intent, site_selection, land_design_briefs, *, run_id: str = "", context_version: str = "", deferral_ledger: Any = None) -> ExecutionPlan:
    """Create self-contained worker tasks keyed only by stable target IDs."""
    intent = _unwrap_intent(intent)
    assignments = {
        item.target_id: item for item in (getattr(site_selection, "target_assignments", None) or [])
    }
    deferred_ids = _deferred_target_ids(deferral_ledger)
    task_specs = (
        ("project", "project_targets"),
        ("zone", "zone_targets"),
        ("facility", "facilities"),
        ("axis", "development_axes"),
        ("road", "road_targets"),
    )
    tasks: list[WorkerTask] = []
    deferred_tasks: list[WorkerTask] = []
    project_task_ids: list[str] = []
    facility_task_ids: list[str] = []
    for target_type, field_name in task_specs:
        for target in _items(intent, field_name):
            target_id = str(getattr(target, "target_id", "") or "")
            if not target_id:
                continue
            assignment = assignments.get(target_id)
            if assignment is None:
                assignment = TargetAssignment(
                    target_id=target_id,
                    target_type=target_type,
                    status="ready",
                    expected_output_kind=getattr(target, "expected_output_kind", "parcel"),
                    target_binding=target.model_dump(mode="json"),
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
                input_artifact_refs=["artifact:intent_compilation", "artifact:site_selection"],
            )
            if target_id in deferred_ids:
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
        site_selection=site_selection,
        land_design_briefs=list(land_design_briefs or []),
    )


__all__ = ["build_execution_plan"]
