from app.contracts.planning.approval import ApprovedExecutionInput
from app.contracts.spatial.planned_state_contracts import PlannedState
from app.domain.materialization.atomic_commit import (
    ExecutionBatch,
    commit_execution_batch,
)


def _approved() -> ApprovedExecutionInput:
    return ApprovedExecutionInput(
        approval_id="approval:atomic",
        scenario_set_ref="set:atomic",
        scenario_id="scenario:atomic",
        scenario_ref="scenario-ref:atomic",
        scenario_fingerprint="scenario-fp",
        problem_fingerprint="problem-fp",
        execution_plan_digest="sha256:" + "0" * 64,
        approval_status="auto",
    )


def test_worker_failure_aborts_without_calling_writer() -> None:
    calls: list[PlannedState] = []
    result = commit_execution_batch(
        ExecutionBatch(
            approved_input=_approved(),
            worker_results=[{"status": "succeeded"}, {"status": "failed"}],
            planned_state=PlannedState(),
        ),
        persist=calls.append,
    )
    assert result.status == "aborted"
    assert calls == []


def test_successful_batch_commits_once() -> None:
    calls: list[PlannedState] = []
    planned = PlannedState()
    result = commit_execution_batch(
        ExecutionBatch(
            approved_input=_approved(),
            expected_task_ids=["task:1"],
            worker_results=[{"task_id": "task:1", "status": "succeeded", "feature_ids": ["feature:1"]}],
            planned_state=planned,
        ),
        persist=calls.append,
    )
    assert result.status == "committed"
    assert result.commit_id.startswith("commit:")
    assert calls == [planned]


def test_missing_required_worker_task_aborts_without_calling_writer() -> None:
    calls: list[PlannedState] = []
    result = commit_execution_batch(
        ExecutionBatch(
            approved_input=_approved(),
            expected_task_ids=["task:required"],
            worker_results=[],
            planned_state=PlannedState(),
        ),
        persist=calls.append,
    )
    assert result.status == "aborted"
    assert any("required worker task results are missing" in item for item in result.diagnostics)
    assert calls == []


def test_missing_approval_aborts_without_calling_writer() -> None:
    calls: list[PlannedState] = []
    result = commit_execution_batch(
        ExecutionBatch(
            approved_input=None,
            expected_task_ids=["task:1"],
            worker_results=[{"task_id": "task:1", "status": "succeeded"}],
            planned_state=PlannedState(),
        ),
        persist=calls.append,
    )
    assert result.status == "aborted"
    assert any("approved execution input is missing" in item for item in result.diagnostics)
    assert result.commit_id == ""
    assert calls == []


def test_deferred_required_worker_aborts_without_calling_writer() -> None:
    calls: list[PlannedState] = []
    result = commit_execution_batch(
        ExecutionBatch(
            approved_input=_approved(),
            expected_task_ids=["task:1"],
            worker_results=[{"task_id": "task:1", "status": "deferred"}],
            planned_state=PlannedState(),
        ),
        persist=calls.append,
    )
    assert result.status == "aborted"
    assert any("not succeeded" in item for item in result.diagnostics)
    assert calls == []


def test_unexpected_required_worker_result_aborts_without_calling_writer() -> None:
    calls: list[PlannedState] = []
    result = commit_execution_batch(
        ExecutionBatch(
            approved_input=_approved(),
            expected_task_ids=["task:expected"],
            worker_results=[
                {"task_id": "task:expected", "status": "succeeded"},
                {"task_id": "task:unexpected", "status": "succeeded"},
            ],
            planned_state=PlannedState(),
        ),
        persist=calls.append,
    )
    assert result.status == "aborted"
    assert any("unexpected worker task results" in item for item in result.diagnostics)
    assert calls == []


def test_empty_expected_task_ids_aborts_without_calling_writer() -> None:
    calls: list[PlannedState] = []
    result = commit_execution_batch(
        ExecutionBatch(
            approved_input=_approved().model_copy(
                update={"execution_plan_digest": "plan:digest"}
            ),
            expected_task_ids=[],
            worker_results=[],
            planned_state=PlannedState(),
        ),
        persist=calls.append,
    )
    assert result.status == "aborted"
    assert any("expected task ids" in item for item in result.diagnostics)
    assert calls == []


def test_duplicate_expected_task_ids_abort_without_calling_writer() -> None:
    calls: list[PlannedState] = []
    result = commit_execution_batch(
        ExecutionBatch(
            approved_input=_approved(),
            expected_task_ids=["task:1", "task:1"],
            worker_results=[{"task_id": "task:1", "status": "succeeded"}],
            planned_state=PlannedState(),
        ),
        persist=calls.append,
    )
    assert result.status == "aborted"
    assert any("non-empty and unique" in item for item in result.diagnostics)
    assert calls == []
