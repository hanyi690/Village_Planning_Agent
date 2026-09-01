"""EXECUTE routing and input-preparation nodes."""

from __future__ import annotations

from typing import Any, Dict

from app.modules.execute.execute_state import ExecuteAgentState
from app.modules.execute.workers.common import _execution_error
from app.modules.execute.workers.worker_common import (
    _execution_intent_from_plan,
    _plan_tasks,
    worker_route_key,
)
from app.infrastructure.logging import get_logger

logger = get_logger(__name__)


async def _route_tasks_node(state: ExecuteAgentState) -> dict:
    """Determine which execution sub-tasks to run based on intent.

    Layout is the core allocation task. Facility, axis, and road tasks are
    routed only when the execution plan declares corresponding targets.
    """
    import os

    # A resumed run may have rebuilt the session KG from its durable Layer-1
    # snapshot.  That rebuild intentionally drops volatile L3 intent triples,
    # so restore the intent layer at this boundary before validating it.  The
    # route node owns this check and must validate the same KG instance that
    # the workers will use, rather than relying on an earlier in-memory write.
    plan_tasks = _plan_tasks(state)
    clean_execution_errors = [
        item for item in (state.execution_errors or [])
        if str(item.get("stage", "")) != "route"
    ]
    error_state = state.model_copy(update={"execution_errors": clean_execution_errors})
    if state.execution_plan is None:
        return _execution_error(error_state, "route", "missing_execution_plan", "EXECUTE requires an ExecutionPlan.")
    tasks = []
    defer_road = os.getenv("GIS_DEFER_ROAD", "").strip().lower() in {"1", "true", "yes"}
    worker_types = {getattr(task, "worker_type", "") for task in plan_tasks}
    route_keys = {worker_route_key(worker_type) for worker_type in worker_types}
    for route_key in ("site_area", "layout", "facility", "axis", "action"):
        if route_key in route_keys:
            tasks.append(route_key)
    if "road" in route_keys and not defer_road:
        tasks.append("road")
    elif "road" in route_keys and defer_road:
        logger.warning("[EXECUTE] road task deferred by GIS_DEFER_ROAD")
    logger.info("[EXECUTE] tasks routed: %s", tasks)
    result = {"tasks_to_run": tasks}
    session_id = getattr(state, "session_id", "")
    bound_intent = _execution_intent_from_plan(state)
    if session_id and bound_intent is not None:
        world_model_commit = getattr(
            getattr(state, "ports", None),
            "world_model_commit",
            None,
        )
        if world_model_commit is None:
            return _execution_error(
                error_state,
                "route",
                "missing_world_model_commit_port",
                "EXECUTE requires the injected world-model commit port.",
            ) | result
        try:
            outcome = world_model_commit.ensure_intent(bound_intent)
            if str(outcome.get("status", "")) != "committed":
                return _execution_error(
                    error_state,
                    "route",
                    "kg_l3_intent_mismatch",
                    "World-model intent commit did not produce a committed result.",
                ) | result
        except Exception as e:
            return _execution_error(
                error_state,
                "route",
                "kg_l3_validation_failed",
                f"KG_L3_VALIDATION_FAILED:{type(e).__name__}",
            ) | result
    return {**result, "execution_errors": clean_execution_errors}


async def _prepare_inputs_node(state: ExecuteAgentState) -> dict:
    """Prepare execution inputs: parcel index plus the immutable ExecutionPlan.

    This is the single compile-entry point for the task-level worker graph.
    Planning revisions must produce a new ExecutionPlan upstream; EXECUTE does
    not mutate target intent while preparing inputs.
    """
    # Approved spatial operations have already resolved DATA-owned
    # resource/representation/geometry references. BSM is source metadata,
    # never an execution-mode switch and never a reason to rebuild a parcel
    # index from a fixed land-use layer.
    spatial_tasks = {"site_area", "layout", "facility", "axis", "road"}
    has_spatial_tasks = bool(spatial_tasks.intersection(state.tasks_to_run or []))
    execution_plan = state.execution_plan
    return {
        "parcel_by_bsm": {},
        "parcel_compatibility_mode": (
            "generic_data" if has_spatial_tasks else "not_applicable"
        ),
        "execution_plan": execution_plan,
    }


async def _task_level_execution_node(state: ExecuteAgentState) -> dict:
    """Execute the immutable plan in actual dependency batches.

    The surrounding LangGraph remains responsible for artifact boundaries;
    this node owns task-level ordering.  An isolation-group plan is passed to
    each worker invocation: unrelated tasks stay isolated, while site
    footprints that explicitly share one source BSM are sent together so the
    worker can enforce one capacity/remainder ledger.  Unsupported utility
    tasks remain durable deferred results and defer their descendants through
    the scheduler.
    """
    from app.contracts.execute.execution_plan_contracts import (
        TaskExecutionResult,
        WorkerResult,
    )
    from app.modules.execute.task_scheduler import schedule_tasks
    from app.modules.execute.workers.action_worker import _action_worker
    from app.modules.execute.workers.axis_worker import _axis_worker
    from app.modules.execute.workers.facility_worker import _facility_worker
    from app.modules.execute.workers.project_worker import _project_worker
    from app.modules.execute.workers.road_worker import _road_worker
    from app.modules.execute.workers.zone_worker import _zone_worker

    plan = state.execution_plan
    if plan is None:
        return _execution_error(
            state, "execute", "missing_execution_plan", "Task scheduler requires an ExecutionPlan."
        )
    all_tasks = list(getattr(plan, "worker_tasks", None) or []) + list(
        getattr(plan, "deferred_tasks", None) or []
    )
    schedule = schedule_tasks(all_tasks)
    if schedule.fail_closed:
        return {
            **_execution_error(
                state,
                "execute",
                "execution_dag_invalid",
                "; ".join(str(item.get("code", "invalid_graph")) for item in schedule.diagnostics),
            ),
            "task_schedule": schedule,
        }

    runners = {
        "site_area_footprint": _project_worker,
        "parcel_transformation": _zone_worker,
        "facility_placement": _facility_worker,
        "road_construction": _road_worker,
        "axis_construction": _axis_worker,
        "non_spatial_action": _action_worker,
    }
    by_id = {
        str(getattr(task, "task_id", "")): task
        for task in all_tasks
        if str(getattr(task, "task_id", ""))
    }
    outputs: list[Any] = []
    trace: list[dict[str, Any]] = []
    sequence = 0
    candidate_geometry_by_id = getattr(state, "candidate_geometry_by_id", {}) or {}

    def _candidate_value(candidate: Any, name: str, default: Any = None) -> Any:
        if isinstance(candidate, dict):
            return candidate.get(name, default)
        return getattr(candidate, name, default)

    def _task_groups(task_ids: list[str]) -> list[list[str]]:
        """Keep same-source site footprints in one resource transaction.

        The project worker emits one preserved remainder for a shared source
        parcel.  Filtering every task to a singleton would make that worker
        recreate the same source remainder once per target.  Only explicit
        source-BSM site-footprint tasks are grouped; all other tasks retain
        the scheduler's one-task isolation.
        """
        groups: list[list[str]] = []
        shared: dict[tuple[str, str], list[str]] = {}
        for task_id in task_ids:
            task = by_id[task_id]
            worker_type = str(
                getattr(getattr(task, "worker_type", ""), "value", getattr(task, "worker_type", ""))
            )
            candidate_id = str(getattr(task, "candidate_id", "") or "")
            candidate = candidate_geometry_by_id.get(candidate_id)
            source_bsms = [
                str(item)
                for item in (_candidate_value(candidate, "source_bsms", None) or [])
                if str(item)
            ]
            materialization_role = str(
                _candidate_value(candidate, "materialization_role", "") or ""
            )
            if (
                worker_type == "site_area_footprint"
                and materialization_role == "site_footprint"
                and len(source_bsms) == 1
            ):
                shared.setdefault((worker_type, source_bsms[0]), []).append(task_id)
            else:
                groups.append([task_id])
        groups.extend(shared.values())
        return groups

    for batch in schedule.batches:
        for task_group in _task_groups(list(batch.task_ids)):
            tasks = [by_id[task_id] for task_id in task_group]
            filtered_plan = plan.model_copy(update={
                "worker_tasks": tasks,
                "deferred_tasks": [],
            })
            task_state = state.model_copy(update={
                "execution_plan": filtered_plan,
                "worker_results": list(outputs),
            })
            task = tasks[0]
            task_id = task_group[0]
            worker_type = str(getattr(getattr(task, "worker_type", ""), "value", getattr(task, "worker_type", "")))
            for grouped_task_id in task_group:
                trace.append({"task_id": grouped_task_id, "event": "start", "sequence": sequence})
            runner = runners.get(worker_type)
            if runner is None:
                result = WorkerResult(
                    worker_type=worker_type,
                    task_id=task_id,
                    task_results=[TaskExecutionResult(
                        task_id=task_id,
                        target_id=str(getattr(task, "target_id", "")),
                        status="deferred",
                        expected_output_kind=getattr(task, "expected_output_kind", "polygon"),
                        errors=["unsupported_capability"],
                        diagnostics=[{"code": "unsupported_capability", "required_capability": getattr(task, "required_capability", "")}],
                    )],
                    unresolved_items=[{"code": "unsupported_capability", "target_id": getattr(task, "target_id", "")}],
                )
            else:
                try:
                    result = runner(task_state)
                    if len(task_group) == 1:
                        result.task_id = task_id
                except Exception as exc:
                    result = WorkerResult(
                        worker_type=worker_type,
                        task_id=task_id,
                        task_results=[TaskExecutionResult(
                            task_id=task_id,
                            target_id=str(getattr(task, "target_id", "")),
                            status="failed",
                            expected_output_kind=getattr(task, "expected_output_kind", "polygon"),
                            errors=[f"WORKER_RAISED:{type(exc).__name__}"],
                        )],
                        unresolved_items=[{"code": "worker_raised", "target_id": getattr(task, "target_id", ""), "exception_type": type(exc).__name__}],
                    )
            sequence += 1
            for grouped_task_id in task_group:
                trace.append({"task_id": grouped_task_id, "event": "complete", "sequence": sequence})
            outputs.append(result)

    for task_id in schedule.deferred_task_ids:
        task = by_id[task_id]
        outputs.append(WorkerResult(
            worker_type=str(getattr(getattr(task, "worker_type", ""), "value", getattr(task, "worker_type", ""))),
            task_id=task_id,
            task_results=[TaskExecutionResult(
                task_id=task_id,
                target_id=str(getattr(task, "target_id", "")),
                status="deferred",
                expected_output_kind=getattr(task, "expected_output_kind", "polygon"),
                errors=["dependency_deferred"],
            )],
            unresolved_items=[{"code": "dependency_deferred", "target_id": getattr(task, "target_id", "")}],
        ))
    return {
        "worker_results": outputs,
        "task_schedule": schedule,
        "execution_trace": trace,
    }
