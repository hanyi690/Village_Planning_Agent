"""EXECUTE Agent - spatial execution subgraph.

Execution orchestration follows the current EXECUTE boundary in docs/design/03_PLANNING_EXECUTION.md.

Consumes approval-bound scenario inputs and compiles them into a complete
PlannedState via the task-scheduled worker boundary (Wave O):

    approval_boundary -> route_tasks -> prepare_inputs -> task_scheduler
      -> merge_worker_results -> geometry_materialize -> planned_state_builder
      -> execution_review

``task_scheduler`` dispatches typed worker functions and preserves each task's
lineage. Worker-specific graph nodes are deliberately not registered: keeping
the old per-worker nodes beside the scheduler created a second, unreachable
execution surface and made the graph claim parallelism that production does
not use.

Nodes call domain services directly rather than LangChain tool wrappers.
"""

from __future__ import annotations

from typing import Literal

from langgraph.graph import StateGraph, END, START

from app.domain.materialization.execute_state import ExecuteAgentState
from app.domain.materialization.nodes import (
    _checkpoint_safe_node,
    _execution_review_node,
    _geometry_materialize_node,
    _merge_worker_results_node,
    _planned_state_builder_node,
    _prepare_inputs_node,
    _route_tasks_node,
    _task_level_execution_node,
)
from app.infrastructure.logging import get_logger

logger = get_logger(__name__)


async def _approval_boundary_node(state: ExecuteAgentState) -> dict:
    """Reject direct graph callers that do not carry the immutable approval."""
    approval = state.approved_execution_input
    if approval is None:
        raise ValueError("EXECUTE graph requires an ApprovedExecutionInput")
    if not approval.can_execute:
        raise ValueError("EXECUTE graph requires an executable ApprovedExecutionInput")
    if not state.approved_input_fingerprint or state.approved_input_fingerprint != approval.fingerprint:
        raise ValueError("EXECUTE graph approval fingerprint is stale")
    try:
        approval.assert_execution_plan_matches(state.execution_plan)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"EXECUTE graph plan is not derived from the approved input: {exc}") from exc
    return {}


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

    Wave O task-scheduled worker boundary:
        approval_boundary -> route_tasks -> prepare_inputs -> task_scheduler
          -> merge_worker_results -> geometry_materialize
          -> planned_state_builder -> execution_review

    The scheduler invokes typed worker functions for each approved task; the
    worker functions are not reachable graph nodes.
    Execution-review retry loop on failure (max 3 rounds -> human review).
    """
    graph = StateGraph(ExecuteAgentState)

    graph.add_node("approval_boundary", _checkpoint_safe_node(_approval_boundary_node))
    graph.add_node("route_tasks", _checkpoint_safe_node(_route_tasks_node))
    graph.add_node("prepare_inputs", _checkpoint_safe_node(_prepare_inputs_node))
    graph.add_node("task_scheduler", _checkpoint_safe_node(_task_level_execution_node))
    graph.add_node("merge_worker_results", _checkpoint_safe_node(_merge_worker_results_node))
    graph.add_node("geometry_materialize", _checkpoint_safe_node(_geometry_materialize_node))
    graph.add_node("planned_state_builder", _checkpoint_safe_node(_planned_state_builder_node))
    graph.add_node("execution_review", _checkpoint_safe_node(_execution_review_node))

    graph.add_edge(START, "approval_boundary")
    graph.add_edge("approval_boundary", "route_tasks")
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
        "[EXECUTE] Agent graph compiled: 8 reachable nodes (task-scheduled workers), 1 conditional edge"
    )
    return compiled


__all__ = [
    "build_execute_agent_graph",
    "_approval_boundary_node",
    "_route_after_execution_review",
]
