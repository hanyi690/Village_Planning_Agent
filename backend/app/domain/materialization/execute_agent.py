"""EXECUTE Agent - spatial execution subgraph.

Migrated from agent/gis/execute/agent.py per docs/architecture/agent-graph.md §5.

Consumes target projection + SELECT SiteSelectionDecision, compiles them into a
complete PlannedState via the multi-worker subgraph (Wave O):

    route_tasks -> prepare_inputs -> project_worker -> zone_worker
      -> [facility_worker || axis_worker]   (LangGraph parallel fan-out)
      -> road_worker -> merge_worker_results -> geometry_materialize
      -> planned_state_builder -> execution_review

This module is now the graph builder only. The 11 node functions live in
``app.domain.materialization.nodes`` (one module per responsibility); worker outputs
cross the boundary through typed contracts.

Nodes call domain services directly rather than LangChain tool wrappers.
"""

from __future__ import annotations

from typing import Literal

from langgraph.graph import StateGraph, END, START

from app.domain.materialization.execute_state import ExecuteAgentState
from app.domain.materialization.nodes import (
    _axis_worker,
    _axis_worker_node,
    _action_worker,
    _action_worker_node,
    _checkpoint_safe,
    _checkpoint_safe_node,
    _execution_error,
    _execution_review_node,
    _facility_worker,
    _facility_worker_node,
    _geometry_materialize_node,
    _merge_worker_results_node,
    _planned_state_builder_node,
    _prepare_inputs_node,
    _project_worker,
    _project_worker_node,
    _road_worker,
    _road_worker_node,
    _route_tasks_node,
    _task_level_execution_node,
    _write_l4_node,
    _zone_worker,
    _zone_worker_node,
)
from app.domain.materialization.nodes.worker_common import _build_parcel_by_bsm
from app.infrastructure.logging import get_logger

logger = get_logger(__name__)


def _route_after_execution_review(
    state: ExecuteAgentState,
) -> Literal["pass", "retry", "retry_route", "human"]:
    """Route after review, retrying route failures from the route boundary."""
    result = state.validation_result or {}
    if result.get("passed", False):
        return "pass"
    if state.validation_round >= 3:
        logger.warning(
            "[EXECUTE] execution review exceeded %d rounds - routing to human review",
            state.validation_round,
        )
        return "human"
    if any(
        str(item.get("stage", "")) == "route"
        for item in (state.execution_errors or [])
    ):
        return "retry_route"
    return "retry"


def build_execute_agent_graph(checkpointer=None):
    """Build the EXECUTE Agent StateGraph.

    Wave O multi-worker subgraph:
        route_tasks -> prepare_inputs -> project_worker -> zone_worker
          -> [facility_worker || axis_worker]  (parallel fan-out diamond)
          -> road_worker -> merge_worker_results -> geometry_materialize
          -> planned_state_builder -> execution_review
    Execution-review retry loop on failure (max 3 rounds -> human review).

    Parallel implementation: a static fan-out diamond - ``zone_worker`` edges
    to both ``facility_worker`` and ``axis_worker`` (LangGraph runs them
    concurrently), which fan back in at ``road_worker``. ``worker_results`` uses
    an upsert reducer so concurrent writes and retry re-runs merge correctly.
    """
    graph = StateGraph(ExecuteAgentState)

    graph.add_node("route_tasks", _checkpoint_safe_node(_route_tasks_node))
    graph.add_node("prepare_inputs", _checkpoint_safe_node(_prepare_inputs_node))
    graph.add_node("task_scheduler", _checkpoint_safe_node(_task_level_execution_node))
    graph.add_node("project_worker", _checkpoint_safe_node(_project_worker_node))
    graph.add_node("zone_worker", _checkpoint_safe_node(_zone_worker_node))
    graph.add_node("facility_worker", _checkpoint_safe_node(_facility_worker_node))
    graph.add_node("axis_worker", _checkpoint_safe_node(_axis_worker_node))
    graph.add_node("action_worker", _checkpoint_safe_node(_action_worker_node))
    graph.add_node("road_worker", _checkpoint_safe_node(_road_worker_node))
    graph.add_node("merge_worker_results", _checkpoint_safe_node(_merge_worker_results_node))
    graph.add_node("geometry_materialize", _checkpoint_safe_node(_geometry_materialize_node))
    graph.add_node("planned_state_builder", _checkpoint_safe_node(_planned_state_builder_node))
    graph.add_node("execution_review", _checkpoint_safe_node(_execution_review_node))

    graph.add_edge(START, "route_tasks")
    graph.add_edge("route_tasks", "prepare_inputs")
    graph.add_edge("prepare_inputs", "task_scheduler")
    graph.add_edge("task_scheduler", "merge_worker_results")
    graph.add_edge("merge_worker_results", "geometry_materialize")
    graph.add_edge("geometry_materialize", "planned_state_builder")
    graph.add_edge("planned_state_builder", "execution_review")

    graph.add_conditional_edges(
        "execution_review",
        _route_after_execution_review,
        {
            "retry": "task_scheduler",
            "retry_route": "route_tasks",
            "pass": END,
            "human": END,
        },
    )

    compile_kwargs = {}
    if checkpointer is not None and checkpointer is not True:
        compile_kwargs["checkpointer"] = checkpointer
    compiled = graph.compile(**compile_kwargs)
    logger.info(
        "[EXECUTE] Agent graph compiled: 11 nodes (multi-worker subgraph), 1 conditional edge"
    )
    return compiled


__all__ = [
    "build_execute_agent_graph",
    "_route_after_execution_review",
    "_checkpoint_safe",
    "_checkpoint_safe_node",
    "_execution_error",
    "_route_tasks_node",
    "_prepare_inputs_node",
    "_task_level_execution_node",
    "_project_worker",
    "_project_worker_node",
    "_zone_worker",
    "_zone_worker_node",
    "_facility_worker",
    "_facility_worker_node",
    "_axis_worker",
    "_axis_worker_node",
    "_action_worker",
    "_action_worker_node",
    "_road_worker",
    "_road_worker_node",
    "_merge_worker_results_node",
    "_geometry_materialize_node",
    "_planned_state_builder_node",
    "_execution_review_node",
    "_write_l4_node",
    "_build_parcel_by_bsm",
]
