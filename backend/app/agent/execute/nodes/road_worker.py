"""Road worker node: planned road network generation."""

from __future__ import annotations

from app.agent.execute.execute_state import ExecuteAgentState
from app.agent.execute.nodes.worker_common import _execution_intent_from_plan, _intent_list, _task_enabled, _task_execution_result
from app.modules.schema.contracts.execution_plan_contracts import WorkerResult
from app.utils.logger import get_logger

logger = get_logger(__name__)


def _road_worker(state: ExecuteAgentState) -> WorkerResult:
    """Road worker: planned road network generation.

    Primary path: the injected ``RoadPlannerPort`` when available; otherwise the
    remote Stage 0-6 generator (confirmation gates 2.6/3/4, ported from
    origin/agent/kg-schema-gis-handoff-20260730), falling back to the
    lightweight local ``plan_roads``. If declared road targets still produce no
    geometry, the worker records an unresolved item (formal output is gated by
    the outer VALIDATE).
    """
    if not _task_enabled(state, "road"):
        return WorkerResult(worker_type="road")

    intent = _execution_intent_from_plan(state)
    road_targets = _intent_list(intent, "road_targets")

    target_ids = {str(road.target_id) for road in road_targets}

    def values(value):
        return {str(item) for item in value} if isinstance(value, list) else {str(value)}

    def layer_target_ids(layers):
        produced = set()
        for layer in layers:
            data = layer.get("data") or layer
            for feature in data.get("features") or []:
                properties = feature.get("properties") or {}
                for key in ("target_id", "project_id", "source_project_id", "source_id", "source_intent_ids", "grouped_source_ids"):
                    produced.update(values(properties.get(key)))
        return produced & target_ids

    def item_target_ids(items):
        matched = {}
        for road in road_targets:
            target_id = str(road.target_id)
            matched[target_id] = [
                item for item in items
                if isinstance(item, dict)
                and target_id in {
                    value
                    for key in ("target_id", "project_id", "source_project_id", "source_id", "source_intent_ids")
                    for value in values(item.get(key))
                }
            ]
        return matched

    def task_results(layers, unresolved_items=None, error=""):
        unresolved_by_target = item_target_ids(list(unresolved_items or []))
        produced = layer_target_ids(layers)
        if len(road_targets) == 1 and layers and not produced:
            produced = {str(road_targets[0].target_id)}
        results = []
        for road in road_targets:
            target_id = str(road.target_id)
            diagnostics = list(unresolved_by_target[target_id])
            succeeded = target_id in produced and not diagnostics and not error
            if not succeeded and not diagnostics:
                diagnostics.append({
                    "code": "road_target_unresolved",
                    "target_id": target_id,
                    "message": "No planned-road output was produced for this target.",
                })
            result = _task_execution_result(
                state,
                "road_construction",
                target_id,
                status="succeeded" if succeeded else "failed",
                diagnostics=diagnostics,
                errors=[error] if error else [],
            )
            if result is not None:
                results.append(result)
        return results

    ports = getattr(state, "ports", None)
    planner = getattr(ports, "road_planner", None) if ports is not None else None
    if planner is not None:
        try:
            if planner.is_available():
                plan_result = planner.plan(state)
                layers = list(getattr(plan_result, "layers", None) or [])
                unresolved_items = list(getattr(plan_result, "unresolved_items", None) or [])
                return WorkerResult(
                    worker_type="road",
                    task_results=task_results(layers, unresolved_items),
                    layers=layers,
                    unresolved_items=unresolved_items,
                    diagnostics=[{"code": "road_planner_port", "available": True}],
                )
        except Exception as e:
            logger.warning("[EXECUTE:road] planner port failed: %s", e)

    generator_error = ""
    try:
        from app.agent.execute.road_generator import (
            execute_road_planning_from_agent_state,
        )

        result = execute_road_planning_from_agent_state(state.model_copy(update={"intent": intent}))
        layers = result.get("layout_layers") or []
        formal_road_layers = [
            layer
            for layer in layers
            if (layer.get("layerType") or layer.get("layer_type"))
            in {"planned_road", "planned_road_candidates"}
            and ((layer.get("data") or {}).get("features") or layer.get("features"))
        ]
        if formal_road_layers:
            for layer in formal_road_layers:
                data = layer.get("data")
                if isinstance(data, dict):
                    data.pop("crs", None)
                layer.pop("crs", None)
            logger.info(
                "[EXECUTE:road] stage generator: ran=%s targets=%d layers=%d",
                result.get("ran"), result.get("road_target_count", 0), len(layers),
            )
            return WorkerResult(
                worker_type="road",
                task_results=task_results(formal_road_layers),
                layers=list(layers),
                diagnostics=[{"code": "road_stage_generator", "ran": bool(result.get("ran"))}],
            )
        logger.info("[EXECUTE:road] stage generator skipped: %s", result.get("reason"))
    except Exception as e:
        generator_error = str(e)
        logger.warning(
            "[EXECUTE:road] stage generator failed, falling back to local plan_roads: %s", e
        )

    logger.warning("[EXECUTE:road] no usable road plan produced; road worker unresolved")
    unresolved_items = [{
        "code": "road_unresolved",
        "message": "No road plan produced: stage generator unavailable or failed.",
    }]
    return WorkerResult(
        worker_type="road",
        task_results=task_results([], unresolved_items, generator_error),
        unresolved_items=unresolved_items,
    )


async def _road_worker_node(state: ExecuteAgentState) -> dict:
    result = _road_worker(state)
    return {"worker_results": [result]}
