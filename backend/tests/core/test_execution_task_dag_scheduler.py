from __future__ import annotations

import asyncio

from app.contracts.domain.selection_contracts import TargetAssignment
from app.contracts.workflow.execution_plan_contracts import WorkerTask, WorkerType
from app.domain.materialization.task_scheduler import schedule_tasks
from app.domain.materialization.execute_state import ExecuteAgentState
from app.domain.materialization.nodes.route_prepare import _task_level_execution_node
from app.contracts.workflow.execution_plan_contracts import ExecutionPlan


def _task(task_id: str, *, deps: list[str] | None = None, deferred: bool = False) -> WorkerTask:
    return WorkerTask(
        task_id=task_id,
        worker_type=WorkerType.FACILITY_PLACEMENT,
        target_id=task_id,
        target_type="facility",
        expected_output_kind="point",
        assignment=TargetAssignment(
            target_id=task_id,
            target_type="facility",
            expected_output_kind="point",
            status="deferred" if deferred else "placed",
        ),
        depends_on=list(deps or []),
        scenario_id="scenario:test",
        candidate_id=f"candidate:{task_id}",
        relation_ids=[f"relation:{task_id}"],
        target_binding={"target_id": task_id},
    )


def test_scheduler_batches_same_and_cross_worker_dependencies() -> None:
    result = schedule_tasks([
        _task("project"),
        _task("facility-a", deps=["project"]),
        _task("facility-b", deps=["project"]),
        _task("road", deps=["facility-a", "facility-b"]),
    ])

    assert result.status == "ready"
    assert [batch.task_ids for batch in result.batches] == [
        ["project"],
        ["facility-a", "facility-b"],
        ["road"],
    ]


def test_scheduler_fails_closed_on_missing_dependency_and_cycle() -> None:
    missing = schedule_tasks([_task("facility", deps=["missing"])])
    assert missing.fail_closed is True
    assert any(item["code"] == "dependency_missing" for item in missing.diagnostics)

    cycle = schedule_tasks([
        _task("a", deps=["b"]),
        _task("b", deps=["a"]),
    ])
    assert cycle.fail_closed is True
    assert any(item["code"] == "dependency_cycle" for item in cycle.diagnostics)


def test_scheduler_propagates_deferred_dependency_without_running_descendant() -> None:
    result = schedule_tasks([
        _task("utility", deferred=True),
        _task("facility", deps=["utility"]),
        _task("project"),
    ])

    assert result.fail_closed is False
    assert result.deferred_task_ids == ["facility", "utility"]
    assert result.runnable_task_ids == ["project"]
    assert any(item["code"] == "dependency_deferred" for item in result.diagnostics)


def test_execute_node_uses_task_batches_and_records_execution_trace() -> None:
    first = WorkerTask(
        task_id="action-a",
        worker_type=WorkerType.NON_SPATIAL_ACTION,
        target_id="action-a",
        target_type="site_area",
        expected_output_kind="action",
        assignment=TargetAssignment(
            target_id="action-a",
            target_type="site_area",
            expected_output_kind="action",
            target_binding={"action": "approve"},
        ),
    )
    second = first.model_copy(deep=True, update={
        "task_id": "action-b",
        "target_id": "action-b",
        "depends_on": ["action-a"],
        "assignment": first.assignment.model_copy(update={
            "target_id": "action-b",
            "target_binding": {"action": "publish"},
        }),
    })
    state = ExecuteAgentState(
        execution_plan=ExecutionPlan(plan_id="plan-actions", worker_tasks=[first, second]),
    )

    update = asyncio.run(_task_level_execution_node(state))

    assert [event["task_id"] for event in update["execution_trace"] if event["event"] == "start"] == [
        "action-a", "action-b"
    ]
    assert [result.task_id for result in update["worker_results"]] == [
        "action-a", "action-b"
    ]
