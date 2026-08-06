"""ExecutionPlan builder (Wave O): thin layer over intent targets + SELECT output."""

from collections import Counter

from app.agent.execute.plan_builder import build_execution_plan
from app.modules.schema.contracts.execution_plan_contracts import (
    ExecutionPlan,
    WorkerType,
)
from app.modules.schema.contracts.parse_contracts import (
    FacilityTarget,
    ProjectTarget,
    RoadTarget,
    SpatialPlanningIntent,
    ZoneTarget,
)
from app.modules.schema.contracts.parse_result_contracts import IntentCompilationResult
from app.modules.schema.contracts.selection_contracts import (
    LandDesignBrief,
    SiteSelectionDecision,
)


def _intent_with_targets():
    return IntentCompilationResult(
        typed_intent=SpatialPlanningIntent(
            project_targets=[
                ProjectTarget(project_id="p1", name="P1"),
                ProjectTarget(project_id="p2", name="P2"),
            ],
            zone_targets=[
                ZoneTarget(zone_id="Z1", land_use="Z1"),
                ZoneTarget(zone_id="Z2", land_use="Z2"),
            ],
            facilities=[
                FacilityTarget(type="school"),
                FacilityTarget(type="clinic"),
            ],
            road_targets=[
                RoadTarget(road_level="主干道"),
                RoadTarget(road_level="支路"),
            ],
        )
    )


def _decision():
    return SiteSelectionDecision(selected_combination=["P001", "P002"])


def test_build_execution_plan_generates_all_worker_tasks():
    plan = build_execution_plan(
        _intent_with_targets(),
        _decision(),
        [LandDesignBrief(project_ref="p1")],
        run_id="r1",
        context_version="v1",
    )

    assert isinstance(plan, ExecutionPlan)
    assert plan.plan_id == "execute-r1"
    assert plan.context_version == "v1"
    assert plan.site_selection.selected_combination == ["P001", "P002"]
    assert len(plan.land_design_briefs) == 1

    counts = Counter(task.worker_type for task in plan.worker_tasks)
    assert counts[WorkerType.PROJECT_FOOTPRINT] == 2
    assert counts[WorkerType.PARCEL_TRANSFORMATION] == 2
    assert counts[WorkerType.FACILITY_PLACEMENT] == 2
    assert counts[WorkerType.ROAD_CONSTRUCTION] == 2


def test_build_execution_plan_dependencies():
    plan = build_execution_plan(_intent_with_targets(), _decision(), [])

    by_id = {task.task_id: task for task in plan.worker_tasks}
    assert by_id["project-p1"].worker_type == WorkerType.PROJECT_FOOTPRINT
    assert by_id["project-p1"].payload == {"project_id": "p1"}
    assert by_id["zone-Z1"].depends_on == ["project-p1", "project-p2"]
    assert by_id["zone-Z2"].depends_on == ["project-p1", "project-p2"]
    assert by_id["facility-school"].depends_on == []
    assert by_id["road-主干道"].depends_on == [
        "project-p1", "project-p2", "facility-school", "facility-clinic",
    ]

    deps = {(d["from"], d["to"]) for d in plan.dependencies}
    assert ("project-p1", "zone-Z1") in deps
    assert ("project-p2", "zone-Z2") in deps
    assert ("project-p1", "road-主干道") in deps
    assert ("facility-school", "road-主干道") in deps
    assert len(plan.dependencies) == len(deps)


def test_build_execution_plan_empty_intent_returns_no_tasks():
    plan = build_execution_plan(None, None, [], run_id="r1")
    assert plan.worker_tasks == []
    assert plan.dependencies == []
    assert plan.plan_id == "execute-r1"


def test_build_execution_plan_accepts_typed_intent_directly():
    intent = SpatialPlanningIntent(
        project_targets=[ProjectTarget(project_id="p9", name="P9")]
    )
    plan = build_execution_plan(intent, None, [])
    assert [task.task_id for task in plan.worker_tasks] == ["project-p9"]
