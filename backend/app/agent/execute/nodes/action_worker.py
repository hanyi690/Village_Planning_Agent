"""Plan-bound worker for non-spatial intervention targets."""

from __future__ import annotations

from app.agent.execute.execute_state import ExecuteAgentState
from app.agent.execute.nodes.worker_common import _plan_tasks, _task_value, _task_enabled
from app.modules.schema.contracts.execution_plan_contracts import TypedActionResult, WorkerResult


def _action_worker(state: ExecuteAgentState) -> WorkerResult:
    if not _task_enabled(state, "action"):
        return WorkerResult(worker_type="action")
    actions = []
    for task in _plan_tasks(state, {"non_spatial_action"}):
        assignment = _task_value(task, "assignment")
        binding = _task_value(assignment, "target_binding", {}) or {}
        actions.append(
            TypedActionResult(
                target_id=str(_task_value(task, "target_id", "")),
                action=str(binding.get("action") or binding.get("name") or binding.get("type") or ""),
                details={"target_type": _task_value(task, "target_type", "")},
            )
        )
    return WorkerResult(worker_type="action", action_results=actions)


async def _action_worker_node(state: ExecuteAgentState) -> dict:
    return {"worker_results": [_action_worker(state)]}


__all__ = ["_action_worker", "_action_worker_node"]
