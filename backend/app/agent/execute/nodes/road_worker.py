"""Road worker node: planned road network generation."""

from __future__ import annotations

from typing import Any, Dict, List

from app.agent.execute.execute_state import ExecuteAgentState
from app.agent.execute.nodes.worker_common import _intent_list, _task_enabled
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

    intent = state.intent
    road_targets = _intent_list(intent, "road_targets")

    ports = getattr(state, "ports", None)
    planner = getattr(ports, "road_planner", None) if ports is not None else None
    if planner is not None:
        try:
            if planner.is_available():
                plan_result = planner.plan(state)
                return WorkerResult(
                    worker_type="road",
                    layers=list(getattr(plan_result, "layers", None) or []),
                    unresolved_items=list(getattr(plan_result, "unresolved_items", None) or []),
                    diagnostics=[{"code": "road_planner_port", "available": True}],
                )
        except Exception as e:
            logger.warning("[EXECUTE:road] planner port failed: %s", e)

    diagnostic_layers: List[Dict[str, Any]] = []
    try:
        from app.agent.execute.road_generator import (
            execute_road_planning_from_agent_state,
        )

        result = execute_road_planning_from_agent_state(state)
        layers = result.get("layout_layers") or []
        diagnostic_layers = list(layers)
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
                layers=list(layers),
                diagnostics=[{"code": "road_stage_generator", "ran": bool(result.get("ran"))}],
            )
        logger.info("[EXECUTE:road] stage generator skipped: %s", result.get("reason"))
    except Exception as e:
        logger.warning(
            "[EXECUTE:road] stage generator failed, falling back to local plan_roads: %s", e
        )

    logger.warning("[EXECUTE:road] no usable road plan produced; road worker unresolved")
    return WorkerResult(
        worker_type="road",
        unresolved_items=[{
            "code": "road_unresolved",
            "message": "No road plan produced: stage generator unavailable or failed.",
        }],
    )


async def _road_worker_node(state: ExecuteAgentState) -> dict:
    result = _road_worker(state)
    return {"worker_results": [result]}