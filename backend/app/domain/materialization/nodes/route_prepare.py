"""EXECUTE routing and input-preparation nodes."""

from __future__ import annotations

from typing import Any, Dict

from app.domain.materialization.execute_state import ExecuteAgentState
from app.domain.materialization.nodes.common import _execution_error
from app.domain.materialization.nodes.constraints import _apply_constraint_adjustments
from app.domain.materialization.nodes.worker_common import _build_parcel_by_bsm, _execution_intent_from_plan, _intent_list, _plan_tasks, worker_route_key
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
        try:
            from rdflib import RDF
            from app.infrastructure.kg.manager import get_kg_manager
            from app.infrastructure.kg.ontology import EntityTypes, PLN

            kg = get_kg_manager().get_session_kg(session_id)
            if kg is None:
                return _execution_error(
                    error_state,
                    "route",
                    "missing_session_kg",
                    "Session KG is required before EXECUTE.",
                ) | result
            from app.infrastructure.kg.builder.layer3 import build_intent_layer

            build_intent_layer(kg, bound_intent)
            expected = {
                EntityTypes.SiteAreaTarget: {
                    str(item.target_id) for item in (getattr(bound_intent, "site_area_targets", None) or [])
                },
                EntityTypes.ZoneTarget: {
                    str(item.target_id) for item in (getattr(bound_intent, "zone_targets", None) or [])
                },
                EntityTypes.FacilityTarget: {
                    str(item.target_id) for item in (getattr(bound_intent, "facilities", None) or [])
                },
                EntityTypes.AxisTarget: {
                    str(item.target_id) for item in (getattr(bound_intent, "development_axes", None) or [])
                },
                EntityTypes.RoadTarget: {
                    str(item.target_id) for item in (getattr(bound_intent, "road_targets", None) or [])
                },
                EntityTypes.LinearTarget: {
                    str(item.target_id) for item in (getattr(bound_intent, "linear_targets", None) or [])
                },
            }
            mismatches = []
            for entity_type, expected_ids in expected.items():
                if not expected_ids:
                    continue
                subjects = set(kg.g.subjects(RDF.type, entity_type))
                actual_ids = {
                    str(target_id)
                    for subject in subjects
                    for target_id in kg.g.objects(subject, PLN.target_id)
                }
                missing_ids = expected_ids - actual_ids
                if actual_ids and missing_ids:
                    mismatches.append(
                        f"{entity_type.split('/')[-1]} missing={sorted(missing_ids)}"
                    )
                elif not actual_ids and len(subjects) < len(expected_ids):
                    mismatches.append(
                        f"{entity_type.split('/')[-1]} state={len(expected_ids)} kg={len(subjects)}"
                    )
            if mismatches:
                return _execution_error(
                    error_state,
                    "route",
                    "kg_l3_intent_mismatch",
                    "L3 intent mismatch: " + "; ".join(mismatches),
                ) | result
        except Exception as e:
            return _execution_error(
                error_state,
                "route",
                "kg_l3_validation_failed",
                str(e),
            ) | result
    return {**result, "execution_errors": clean_execution_errors}


async def _prepare_inputs_node(state: ExecuteAgentState) -> dict:
    """Prepare execution inputs: parcel_by_bsm + constraint adjustments + ExecutionPlan.

    This is the single compile-entry point: it builds the parcel index once and
    applies any constraint_adjustments to the zone targets (legacy retry-loop
    shape) so the workers consume consistent inputs.
    """
    # Action-only plans do not have a spatial parcel input.  Do not require a
    # GIS bundle for a non-spatial execution branch; spatial workers validate
    # the bundle when they are actually routed.
    parcel_by_bsm = _build_parcel_by_bsm(state) if state.spatial_workspace is not None else {}
    zone_targets = _intent_list(_execution_intent_from_plan(state), "zone_targets")
    applied = _apply_constraint_adjustments(
        zone_targets, list(state.constraint_adjustments or [])
    )
    execution_plan = state.execution_plan
    return {
        "parcel_by_bsm": parcel_by_bsm,
        "constraint_adjustments": applied,
        "execution_plan": execution_plan,
    }


async def _task_level_execution_node(state: ExecuteAgentState) -> dict:
    """Execute the immutable plan in actual dependency batches.

    The surrounding LangGraph remains responsible for artifact boundaries;
    this node owns task-level ordering.  A filtered plan is passed to each
    worker invocation, so workers cannot accidentally consume a sibling task
    from the same worker-type batch.  Unsupported utility tasks remain durable
    deferred results and defer their descendants through the scheduler.
    """
    from app.contracts.workflow.execution_plan_contracts import (
        TaskExecutionResult,
        WorkerResult,
    )
    from app.domain.materialization.task_scheduler import schedule_tasks
    from app.domain.materialization.nodes.action_worker import _action_worker
    from app.domain.materialization.nodes.axis_worker import _axis_worker
    from app.domain.materialization.nodes.facility_worker import _facility_worker
    from app.domain.materialization.nodes.project_worker import _project_worker
    from app.domain.materialization.nodes.road_worker import _road_worker
    from app.domain.materialization.nodes.zone_worker import _zone_worker

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
    for batch in schedule.batches:
        for task_id in batch.task_ids:
            task = by_id[task_id]
            filtered_plan = plan.model_copy(update={
                "worker_tasks": [task],
                "deferred_tasks": [],
            })
            task_state = state.model_copy(update={
                "execution_plan": filtered_plan,
                "worker_results": list(outputs),
            })
            worker_type = str(getattr(getattr(task, "worker_type", ""), "value", getattr(task, "worker_type", "")))
            trace.append({"task_id": task_id, "event": "start", "sequence": sequence})
            runner = runners.get(worker_type)
            if runner is None:
                result = WorkerResult(
                    worker_type=worker_type,
                    task_id=task_id,
                    task_results=[TaskExecutionResult(
                        task_id=task_id,
                        target_id=str(getattr(task, "target_id", "")),
                        status="deferred",
                        expected_output_kind=getattr(task, "expected_output_kind", "parcel"),
                        errors=["unsupported_capability"],
                        diagnostics=[{"code": "unsupported_capability", "required_capability": getattr(task, "required_capability", "")}],
                    )],
                    unresolved_items=[{"code": "unsupported_capability", "target_id": getattr(task, "target_id", "")}],
                )
            else:
                try:
                    result = runner(task_state)
                    result.task_id = task_id
                except Exception as exc:
                    result = WorkerResult(
                        worker_type=worker_type,
                        task_id=task_id,
                        task_results=[TaskExecutionResult(
                            task_id=task_id,
                            target_id=str(getattr(task, "target_id", "")),
                            status="failed",
                            expected_output_kind=getattr(task, "expected_output_kind", "parcel"),
                            errors=[str(exc)],
                        )],
                        unresolved_items=[{"code": "worker_raised", "target_id": getattr(task, "target_id", ""), "message": str(exc)}],
                    )
            sequence += 1
            trace.append({"task_id": task_id, "event": "complete", "sequence": sequence})
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
                expected_output_kind=getattr(task, "expected_output_kind", "parcel"),
                errors=["dependency_deferred"],
            )],
            unresolved_items=[{"code": "dependency_deferred", "target_id": getattr(task, "target_id", "")}],
        ))
    return {
        "worker_results": outputs,
        "task_schedule": schedule,
        "execution_trace": trace,
    }
