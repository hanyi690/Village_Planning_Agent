"""EXECUTE routing and input-preparation nodes."""

from __future__ import annotations

from typing import Any, Dict

from app.agent.execute.execute_state import ExecuteAgentState
from app.agent.execute.nodes.common import _execution_error
from app.agent.execute.nodes.constraints import _apply_constraint_adjustments
from app.agent.execute.nodes.worker_common import _build_parcel_by_bsm, _intent_list
from app.utils.logger import get_logger

logger = get_logger(__name__)


async def _route_tasks_node(state: ExecuteAgentState) -> dict:
    """Determine which execution sub-tasks to run based on intent.

    Layout is the core allocation task. Facility, axis, and road tasks are
    routed only when the typed or legacy intent declares corresponding targets.
    """
    import os

    tasks = ["layout"]
    defer_road = os.getenv("GIS_DEFER_ROAD", "").strip().lower() in {"1", "true", "yes"}
    intent = state.intent
    if intent is not None:
        if isinstance(intent, dict):
            projects = intent.get("project_targets")
            facilities = intent.get("facilities")
            development_axes = intent.get("development_axes")
            road_targets = intent.get("road_targets")
        else:
            projects = getattr(intent, "project_targets", None)
            facilities = getattr(intent, "facilities", None)
            development_axes = getattr(intent, "development_axes", None)
            road_targets = getattr(intent, "road_targets", None)
        if projects:
            tasks.append("project")
        if facilities:
            tasks.append("facility")
        if development_axes:
            tasks.append("axis")
        if road_targets and not defer_road:
            tasks.append("road")
        elif road_targets and defer_road:
            logger.warning("[EXECUTE] road task deferred by GIS_DEFER_ROAD")
    logger.info("[EXECUTE] tasks routed: %s", tasks)
    result = {"tasks_to_run": tasks}
    session_id = getattr(state, "session_id", "")
    if session_id and intent is not None:
        try:
            from rdflib import RDF
            from app.modules.kg.manager import get_kg_manager
            from app.modules.kg.ontology import EntityTypes

            kg = get_kg_manager().get_session_kg(session_id)
            if kg is None:
                return _execution_error(
                    state,
                    "route",
                    "missing_session_kg",
                    "Session KG is required before EXECUTE.",
                ) | result
            expected = {
                EntityTypes.ProjectTarget: len(getattr(intent, "project_targets", None) or []),
                EntityTypes.ZoneTarget: len(getattr(intent, "zone_targets", None) or []),
                EntityTypes.FacilityTarget: len(getattr(intent, "facilities", None) or []),
                EntityTypes.AxisTarget: len(getattr(intent, "development_axes", None) or []),
                EntityTypes.RoadTarget: len(getattr(intent, "road_targets", None) or []),
            }
            mismatches = []
            for entity_type, expected_count in expected.items():
                actual_count = len(set(kg.g.subjects(RDF.type, entity_type)))
                if actual_count != expected_count:
                    mismatches.append(
                        f"{entity_type.split('/')[-1]} state={expected_count} kg={actual_count}"
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
    parcel_by_bsm = _build_parcel_by_bsm(state)
    zone_targets = _intent_list(state.intent, "zone_targets")
    applied = _apply_constraint_adjustments(
        zone_targets, list(state.constraint_adjustments or [])
    )
    execution_plan = state.execution_plan
    return {
        "parcel_by_bsm": parcel_by_bsm,
        "constraint_adjustments": applied,
        "execution_plan": execution_plan,
    }