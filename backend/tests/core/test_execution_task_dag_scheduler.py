from __future__ import annotations

import asyncio
from types import SimpleNamespace

from app.contracts.workflow.materialization_contracts import TargetAssignment
from app.contracts.workflow.execution_plan_contracts import (
    ExecutionPlan,
    TaskExecutionResult,
    WorkerResult,
    WorkerTask,
    WorkerType,
)
from app.contracts.spatial.parcel_change_contracts import ParcelChange
from app.domain.materialization.task_scheduler import schedule_tasks
from app.domain.materialization.execute_state import ExecuteAgentState
from app.domain.materialization.nodes.route_prepare import _task_level_execution_node


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


def test_execute_node_groups_same_source_site_tasks_for_one_remainder(monkeypatch) -> None:
    first = WorkerTask(
        task_id="site-a",
        worker_type=WorkerType.SITE_AREA_FOOTPRINT,
        target_id="site-a",
        target_type="site_area",
        expected_output_kind="polygon",
        assignment=TargetAssignment(
            target_id="site-a",
            target_type="site_area",
            expected_output_kind="polygon",
            status="placed",
        ),
        candidate_id="candidate:site-a",
    )
    second = first.model_copy(deep=True, update={
        "task_id": "site-b",
        "target_id": "site-b",
        "candidate_id": "candidate:site-b",
        "assignment": first.assignment.model_copy(update={"target_id": "site-b"}),
    })
    calls: list[list[str]] = []

    def fake_project_worker(task_state):
        task_ids = [task.task_id for task in task_state.execution_plan.worker_tasks]
        calls.append(task_ids)
        return WorkerResult(
            worker_type="site_area",
            task_results=[
                TaskExecutionResult(
                    task_id=task.task_id,
                    target_id=task.target_id,
                    status="succeeded",
                    expected_output_kind="polygon",
                )
                for task in task_state.execution_plan.worker_tasks
            ],
        )

    monkeypatch.setattr(
        "app.domain.materialization.nodes.project_worker._project_worker",
        fake_project_worker,
    )
    state = ExecuteAgentState(
        execution_plan=ExecutionPlan(worker_tasks=[first, second]),
        candidate_geometry_by_id={
            "candidate:site-a": SimpleNamespace(
                materialization_role="site_footprint",
                source_bsms=["P-SHARED"],
            ),
            "candidate:site-b": SimpleNamespace(
                materialization_role="site_footprint",
                source_bsms=["P-SHARED"],
            ),
        },
    )

    update = asyncio.run(_task_level_execution_node(state))

    assert calls == [["site-a", "site-b"]]
    assert [item.target_id for item in update["worker_results"][0].task_results] == [
        "site-a", "site-b"
    ]


def test_execute_node_keeps_mixed_site_and_facility_workers_isolated_then_merges(
    monkeypatch,
) -> None:
    site = WorkerTask(
        task_id="site-mixed",
        worker_type=WorkerType.SITE_AREA_FOOTPRINT,
        target_id="site-mixed",
        target_type="site_area",
        expected_output_kind="polygon",
        assignment=TargetAssignment(
            target_id="site-mixed",
            target_type="site_area",
            expected_output_kind="polygon",
            status="placed",
        ),
        candidate_id="candidate:site-mixed",
    )
    facility = WorkerTask(
        task_id="facility-mixed",
        worker_type=WorkerType.FACILITY_PLACEMENT,
        target_id="facility-mixed",
        target_type="facility",
        expected_output_kind="point",
        assignment=TargetAssignment(
            target_id="facility-mixed",
            target_type="facility",
            expected_output_kind="point",
            status="placed",
        ),
        candidate_id="candidate:facility-mixed",
    )

    def fake_project_worker(task_state):
        tasks = task_state.execution_plan.worker_tasks
        assert [item.task_id for item in tasks] == ["site-mixed"]
        return WorkerResult(
            worker_type="site_area",
            task_id="site-mixed",
            task_results=[TaskExecutionResult(
                task_id="site-mixed",
                target_id="site-mixed",
                status="succeeded",
                expected_output_kind="polygon",
            )],
            layers=[{
                "layerType": "planned_project",
                "data": {"type": "FeatureCollection", "features": []},
            }],
            parcel_changes=[ParcelChange(
                bsm="site-mixed:footprint",
                action="create",
                after_geometry_wkt="POLYGON ((0 0, 1 0, 1 1, 0 1, 0 0))",
                new_area_ha=1.0,
            )],
        )

    def fake_facility_worker(task_state):
        tasks = task_state.execution_plan.worker_tasks
        assert [item.task_id for item in tasks] == ["facility-mixed"]
        return WorkerResult(
            worker_type="facility",
            task_id="facility-mixed",
            task_results=[TaskExecutionResult(
                task_id="facility-mixed",
                target_id="facility-mixed",
                status="succeeded",
                expected_output_kind="point",
            )],
            layers=[{
                "layerType": "planned_facility",
                "data": {"type": "FeatureCollection", "features": []},
            }],
        )

    monkeypatch.setattr(
        "app.domain.materialization.nodes.project_worker._project_worker",
        fake_project_worker,
    )
    monkeypatch.setattr(
        "app.domain.materialization.nodes.facility_worker._facility_worker",
        fake_facility_worker,
    )
    state = ExecuteAgentState(
        execution_plan=ExecutionPlan(worker_tasks=[site, facility]),
        candidate_geometry_by_id={
            "candidate:site-mixed": SimpleNamespace(
                materialization_role="site_footprint",
                source_bsms=["P-MIXED"],
            ),
            "candidate:facility-mixed": SimpleNamespace(
                materialization_role="facility",
                source_bsms=["P-MIXED"],
            ),
        },
    )

    update = asyncio.run(_task_level_execution_node(state))

    assert {
        item.worker_type for item in update["worker_results"]
    } == {"site_area", "facility"}
    assert {
        event["task_id"]
        for event in update["execution_trace"]
        if event["event"] == "start"
    } == {"site-mixed", "facility-mixed"}

    from app.domain.materialization.nodes.merge_and_materialize import (
        _merge_worker_results_node,
    )

    merged = asyncio.run(_merge_worker_results_node(
        state.model_copy(update={"worker_results": update["worker_results"]})
    ))

    assert merged["worker_conflict_diagnostics"] == []
    assert [change.bsm for change in merged["parcel_changeset"].changes] == [
        "site-mixed:footprint"
    ]
    assert {layer["layerType"] for layer in merged["layout_configs"]} == {
        "planned_project",
        "planned_facility",
    }
