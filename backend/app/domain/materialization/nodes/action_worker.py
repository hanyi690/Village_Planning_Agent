"""Plan-bound worker for non-spatial intervention targets."""

from __future__ import annotations

from app.domain.materialization.execute_state import ExecuteAgentState
from app.domain.materialization.nodes.worker_common import _plan_tasks, _task_value, _task_enabled, _task_execution_result
from app.contracts.workflow.execution_plan_contracts import TypedActionResult, WorkerResult


def _action_worker(state: ExecuteAgentState) -> WorkerResult:
    if not _task_enabled(state, "action"):
        return WorkerResult(worker_type="action")
    actions = []
    task_results = []
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
        task_result = _task_execution_result(
            state,
            "non_spatial_action",
            str(_task_value(task, "target_id", "")),
            task_id=str(_task_value(task, "task_id", "") or ""),
            candidate_id=str(_task_value(task, "candidate_id", "") or ""),
            status="succeeded",
        )
        if task_result is not None:
            task_results.append(task_result)
    return WorkerResult(worker_type="action", action_results=actions, task_results=task_results)

__all__ = ["_action_worker"]
