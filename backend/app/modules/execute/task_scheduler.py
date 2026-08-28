"""Deterministic task-level ExecutionDAG scheduling.

The old EXECUTE graph grouped work by worker type.  That made ``depends_on``
an informational field: two tasks of the same worker (or tasks in different
worker branches) could still run in the same batch.  This module is the small,
side-effect-free scheduling boundary used by EXECUTE.  It accepts the frozen
``WorkerTask`` contract and returns deterministic batches; it never repairs a
bad graph by guessing an order or by dropping a dependency.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


def _value(item: Any, key: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(key, default)
    return getattr(item, key, default)


class TaskBatch(BaseModel):
    """One concurrently executable DAG batch."""

    index: int
    task_ids: list[str] = Field(default_factory=list)


class TaskSchedule(BaseModel):
    """Auditable scheduling result.

    ``failed`` means no task is allowed to run.  ``partial`` means valid
    batches exist but one or more tasks were durably deferred (for example an
    unsupported utility capability).  A dependent task is never runnable when
    one of its dependencies is deferred.
    """

    status: Literal["ready", "partial", "complete", "failed"] = "complete"
    batches: list[TaskBatch] = Field(default_factory=list)
    deferred_task_ids: list[str] = Field(default_factory=list)
    diagnostics: list[dict[str, Any]] = Field(default_factory=list)

    @property
    def runnable_task_ids(self) -> list[str]:
        return [task_id for batch in self.batches for task_id in batch.task_ids]

    @property
    def fail_closed(self) -> bool:
        return self.status == "failed"


def _deferred(task: Any) -> bool:
    assignment = _value(task, "assignment")
    assignment_status = str(_value(assignment, "status", "") or "")
    return assignment_status == "deferred" or bool(
        str(_value(task, "defer_reason", "") or "").strip()
    )


def schedule_tasks(tasks: list[Any]) -> TaskSchedule:
    """Topologically schedule tasks and fail closed on malformed graphs.

    The implementation uses Kahn's algorithm and preserves task list order
    within each batch.  Dependencies are validated against the complete plan,
    including durable deferred tasks, so a deferred utility task cannot be
    silently treated as completed input to a downstream task.
    """

    task_list = list(tasks or [])
    by_id: dict[str, Any] = {}
    diagnostics: list[dict[str, Any]] = []
    for task in task_list:
        task_id = str(
            _value(task, "task_id", _value(task, "task_ref", "")) or ""
        ).strip()
        if not task_id:
            diagnostics.append({"code": "task_id_missing"})
            continue
        if task_id in by_id:
            diagnostics.append({"code": "duplicate_task_id", "task_id": task_id})
            continue
        by_id[task_id] = task

    if diagnostics:
        return TaskSchedule(status="failed", diagnostics=diagnostics)

    dependencies: dict[str, list[str]] = {}
    for task_id, task in by_id.items():
        deps = [
            str(dep).strip()
            for dep in list(_value(task, "depends_on", []) or [])
            if str(dep).strip()
        ]
        missing = sorted(set(dep for dep in deps if dep not in by_id))
        if missing:
            diagnostics.append({
                "code": "dependency_missing",
                "task_id": task_id,
                "missing_dependency_ids": missing,
            })
        dependencies[task_id] = list(dict.fromkeys(deps))
    if diagnostics:
        return TaskSchedule(status="failed", diagnostics=diagnostics)

    deferred_ids = {task_id for task_id, task in by_id.items() if _deferred(task)}
    # A deferred prerequisite permanently defers its descendants.  This is
    # intentionally transitive and runs before Kahn so no invalid batch leaks.
    changed = True
    while changed:
        changed = False
        for task_id, deps in dependencies.items():
            if task_id in deferred_ids:
                continue
            inherited = [dep for dep in deps if dep in deferred_ids]
            if inherited:
                deferred_ids.add(task_id)
                diagnostics.append({
                    "code": "dependency_deferred",
                    "task_id": task_id,
                    "dependency_ids": inherited,
                })
                changed = True

    runnable = [task_id for task_id in by_id if task_id not in deferred_ids]
    completed: set[str] = set()
    batches: list[TaskBatch] = []
    while runnable:
        ready = [
            task_id
            for task_id in runnable
            if all(dep in completed for dep in dependencies[task_id])
        ]
        if not ready:
            diagnostics.append({
                "code": "dependency_cycle",
                "task_ids": list(runnable),
            })
            return TaskSchedule(
                status="failed",
                deferred_task_ids=sorted(deferred_ids),
                diagnostics=diagnostics,
            )
        batches.append(TaskBatch(index=len(batches), task_ids=ready))
        completed.update(ready)
        runnable = [task_id for task_id in runnable if task_id not in completed]

    if diagnostics and batches:
        status: Literal["ready", "partial", "complete", "failed"] = "partial"
    elif deferred_ids:
        status = "partial"
    else:
        status = "ready" if batches else "complete"
    return TaskSchedule(
        status=status,
        batches=batches,
        deferred_task_ids=sorted(deferred_ids),
        diagnostics=diagnostics,
    )


__all__ = ["TaskBatch", "TaskSchedule", "schedule_tasks"]
