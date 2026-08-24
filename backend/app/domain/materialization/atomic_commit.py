"""Pure atomic materialization boundary for EXECUTE worker batches."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Callable

from app.contracts.planning.approval import ApprovedExecutionInput
from app.contracts.spatial.parcel_change_contracts import ParcelChange
from app.contracts.spatial.planned_state_contracts import PlannedState


@dataclass
class ExecutionBatch:
    """All worker output held in memory before a formal write."""

    approved_input: ApprovedExecutionInput | None = None
    expected_task_ids: list[str] = field(default_factory=list)
    worker_results: list[Any] = field(default_factory=list)
    parcel_changes: list[ParcelChange] = field(default_factory=list)
    planned_state: PlannedState | None = None
    diagnostics: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class AtomicCommitResult:
    status: str
    commit_id: str = ""
    diagnostics: tuple[str, ...] = ()
    planned_state: PlannedState | None = None


def _worker_status(result: Any) -> str:
    return str(
        result.get("status", "") if isinstance(result, dict) else getattr(result, "status", "")
    )


def _feature_ids(result: Any) -> list[str]:
    values = result.get("feature_ids", []) if isinstance(result, dict) else getattr(result, "feature_ids", [])
    return [str(value) for value in values if str(value).strip()]


def _task_id(result: Any) -> str:
    value = result.get("task_id", "") if isinstance(result, dict) else getattr(result, "task_id", "")
    return str(value or "").strip()


def commit_execution_batch(
    batch: ExecutionBatch,
    *,
    persist: Callable[[PlannedState], Any] | None = None,
) -> AtomicCommitResult:
    """Validate every worker result, then invoke the writer exactly once.

    A failed validation never calls ``persist`` and therefore cannot expose a
    partial PlannedState.  The writer callback is intentionally injected so
    this boundary can be tested without a live KG or artifact repository.
    """

    diagnostics = [str(item) for item in batch.diagnostics if str(item).strip()]
    if batch.approved_input is None:
        diagnostics.append("approved execution input is missing")
    elif not batch.approved_input.can_execute:
        diagnostics.append("approved execution input is not executable")
    if batch.planned_state is None:
        diagnostics.append("planned state is missing")
    non_successful = [
        item for item in batch.worker_results if _worker_status(item) != "succeeded"
    ]
    if non_successful:
        diagnostics.append("one or more worker results did not succeed")
    expected_values = [str(task_id).strip() for task_id in batch.expected_task_ids]
    expected_task_ids = {task_id for task_id in expected_values if task_id}
    if not expected_values or len(expected_task_ids) != len(expected_values):
        diagnostics.append("expected task ids must be non-empty and unique")
    if any(not task_id for task_id in expected_values):
        diagnostics.append("expected task ids must not be blank")
    actual_values = [_task_id(item) for item in batch.worker_results]
    actual_task_ids = {task_id for task_id in actual_values if task_id}
    if any(not task_id for task_id in actual_values):
        diagnostics.append("worker result task_id is missing")
    duplicate_task_ids = sorted(
        task_id
        for task_id in actual_task_ids
        if actual_values.count(task_id) > 1
    )
    if duplicate_task_ids:
        diagnostics.append("duplicate worker task results: " + ", ".join(duplicate_task_ids))
    if expected_task_ids:
        unexpected_task_ids = sorted(actual_task_ids - expected_task_ids)
        if unexpected_task_ids:
            diagnostics.append(
                "unexpected worker task results: " + ", ".join(unexpected_task_ids)
            )
        missing_task_ids = sorted(expected_task_ids - actual_task_ids)
        if missing_task_ids:
            diagnostics.append(
                "required worker task results are missing: " + ", ".join(missing_task_ids)
            )
        non_successful_expected = sorted(
            task_id
            for task_id, result in zip(actual_values, batch.worker_results)
            if task_id in expected_task_ids and _worker_status(result) != "succeeded"
        )
        if non_successful_expected:
            diagnostics.append(
                "required worker tasks are not succeeded: "
                + ", ".join(non_successful_expected)
            )
    feature_ids = [feature_id for item in batch.worker_results for feature_id in _feature_ids(item)]
    if len(feature_ids) != len(set(feature_ids)):
        diagnostics.append("duplicate materialized feature ids")
    if diagnostics:
        return AtomicCommitResult(
            status="aborted",
            diagnostics=tuple(sorted(set(diagnostics))),
            planned_state=None,
        )
    if persist is not None:
        persist(batch.planned_state)
    raw = "|".join(
        [
            str(getattr(batch.approved_input, "fingerprint", "") or ""),
            str(getattr(batch.planned_state, "artifact_id", "") or ""),
            str(len(batch.worker_results)),
        ]
    ).encode("utf-8")
    return AtomicCommitResult(
        status="committed",
        commit_id=f"commit:{hashlib.sha256(raw).hexdigest()[:20]}",
        diagnostics=(),
        planned_state=batch.planned_state,
    )


__all__ = ["ExecutionBatch", "AtomicCommitResult", "commit_execution_batch"]
