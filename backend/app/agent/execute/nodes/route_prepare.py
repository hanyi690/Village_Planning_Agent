"""EXECUTE routing and input-preparation nodes."""

from __future__ import annotations

from typing import Any, Dict

from app.agent.execute.execute_state import ExecuteAgentState
from app.agent.execute.nodes.common import _execution_error
from app.agent.execute.nodes.constraints import _apply_constraint_adjustments
from app.agent.execute.nodes.worker_common import _build_parcel_by_bsm, _execution_intent_from_plan, _intent_list, _plan_tasks, worker_route_key
from app.utils.logger import get_logger

logger = get_logger(__name__)


async def _route_tasks_node(state: ExecuteAgentState) -> dict:
    """Determine which execution sub-tasks to run based on intent.

    Layout is the core allocation task. Facility, axis, and road tasks are
    routed only when the execution plan declares corresponding targets.
    """
    import os

    plan_tasks = _plan_tasks(state)
    if state.execution_plan is None:
        return _execution_error(state, "route", "missing_execution_plan", "EXECUTE requires an ExecutionPlan.")
    tasks = []
    defer_road = os.getenv("GIS_DEFER_ROAD", "").strip().lower() in {"1", "true", "yes"}
    worker_types = {getattr(task, "worker_type", "") for task in plan_tasks}
    route_keys = {worker_route_key(worker_type) for worker_type in worker_types}
    for route_key in ("project", "layout", "facility", "axis", "action"):
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
            from app.modules.kg.manager import get_kg_manager
            from app.modules.kg.ontology import EntityTypes, PLN

            kg = get_kg_manager().get_session_kg(session_id)
            if kg is None:
                return _execution_error(
                    state,
                    "route",
                    "missing_session_kg",
                    "Session KG is required before EXECUTE.",
                ) | result
            expected = {
                EntityTypes.ProjectTarget: {
                    str(item.target_id) for item in (getattr(bound_intent, "project_targets", None) or [])
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
                    state,
                    "route",
                    "kg_l3_intent_mismatch",
                    "L3 intent mismatch: " + "; ".join(mismatches),
                ) | result
        except Exception as e:
            return _execution_error(
                state,
                "route",
                "kg_l3_validation_failed",
                str(e),
            ) | result
    return result


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
