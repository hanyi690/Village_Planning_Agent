"""ExecutionPlan builder — thin layer over intent targets + SELECT output.

Wave O: EXECUTE consumes ``SiteSelectionDecision + ExecutionPlan``; the
ExecutionPlan is produced here (post-L3 SELECT) rather than assembled inside
EXECUTE, so the worker task list + dependency graph reflect the PARSE intent
targets and the SELECT decision. This is a thin layer: it only generates the
WorkerTask list + dependency edges, and does NOT inject L2 strategy
constraints (that stays with the select/validate layers).
"""

from __future__ import annotations

from typing import Any, List

from app.modules.schema.contracts.execution_plan_contracts import (
    ExecutionPlan,
    WorkerTask,
    WorkerType,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)


def _intent_list(intent: Any, key: str) -> List[Any]:
    """Read a list field off a typed intent or a legacy intent dict."""
    if intent is None:
        return []
    if isinstance(intent, dict):
        value = intent.get(key)
    else:
        value = getattr(intent, key, None)
    return list(value or [])


def _unwrap_intent(intent: Any) -> Any:
    """Unwrap an IntentCompilationResult to its typed SpatialPlanningIntent."""
    if intent is not None and not isinstance(intent, dict):
        typed = getattr(intent, "typed_intent", None)
        if typed is not None:
            return typed
    return intent


def _target_id(item: Any, key: str, fallback_key: str = "") -> str:
    """Defensively read an identifier off a typed target / dict / bare value."""
    if item is None:
        return ""
    if isinstance(item, dict):
        value = item.get(key)
        if not value and fallback_key:
            value = item.get(fallback_key)
    else:
        value = getattr(item, key, None)
        if not value and fallback_key:
            value = getattr(item, fallback_key, None)
    return str(value or "")


def build_execution_plan(
    intent,
    site_selection,
    land_design_briefs,
    *,
    run_id: str = "",
    context_version: str = "",
) -> ExecutionPlan:
    """From intent targets + site_selection generate WorkerTask list + dependency graph.

    Thin layer: only generates the task list + dependency edges; does NOT inject
    L2 strategy constraints.
    """
    intent = _unwrap_intent(intent)
    tasks: List[WorkerTask] = []
    project_task_ids: List[str] = []
    facility_task_ids: List[str] = []

    for index, item in enumerate(_intent_list(intent, "project_targets")):
        project_id = _target_id(item, "project_id")
        if not project_id:
            project_id = f"p{index}"
        task_id = f"project-{project_id}"
        project_task_ids.append(task_id)
        tasks.append(WorkerTask(
            task_id=task_id,
            worker_type=WorkerType.PROJECT_FOOTPRINT,
            payload={"project_id": project_id},
        ))

    for index, item in enumerate(_intent_list(intent, "zone_targets")):
        zone_id = _target_id(item, "zone_id", fallback_key="land_use")
        if not zone_id:
            zone_id = f"z{index}"
        tasks.append(WorkerTask(
            task_id=f"zone-{zone_id}",
            worker_type=WorkerType.PARCEL_TRANSFORMATION,
            payload={"zone_id": zone_id},
            depends_on=list(project_task_ids),
        ))

    for index, item in enumerate(_intent_list(intent, "facilities")):
        facility_type = _target_id(item, "type")
        if not facility_type:
            facility_type = f"f{index}"
        task_id = f"facility-{facility_type}"
        facility_task_ids.append(task_id)
        tasks.append(WorkerTask(
            task_id=task_id,
            worker_type=WorkerType.FACILITY_PLACEMENT,
            payload={"facility_type": facility_type},
        ))

    for index, item in enumerate(_intent_list(intent, "road_targets")):
        road_id = _target_id(item, "road_id", fallback_key="road_level")
        if not road_id:
            road_id = f"r{index}"
        tasks.append(WorkerTask(
            task_id=f"road-{road_id}",
            worker_type=WorkerType.ROAD_CONSTRUCTION,
            payload={"road_id": road_id},
            depends_on=list(project_task_ids) + list(facility_task_ids),
        ))

    dependencies: List[dict] = []
    for task in tasks:
        for dep in task.depends_on:
            dependencies.append({"from": dep, "to": task.task_id})

    return ExecutionPlan(
        plan_id=f"execute-{run_id or 'current'}",
        worker_tasks=tasks,
        dependencies=dependencies,
        context_version=context_version,
        intent=intent,
        site_selection=site_selection,
        land_design_briefs=list(land_design_briefs or []),
    )


__all__ = ["build_execution_plan"]
