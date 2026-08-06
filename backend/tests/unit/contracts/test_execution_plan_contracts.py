"""EXECUTE worker contracts: ExecutionPlan / WorkerResult / allocation contracts (Wave O)."""

from app.modules.schema.contracts.execution_plan_contracts import (
    ExecutionPlan,
    ExecutionResult,
    ParcelAllocationProblem,
    RoadPlanResult,
    WorkerResult,
    WorkerTask,
    WorkerType,
    ZoneAllocationSolution,
    ZoneAssignmentEntry,
)
from app.modules.schema.contracts.parse_contracts import SpatialPlanningIntent
from app.modules.schema.contracts.selection_contracts import LandDesignBrief, SiteSelectionDecision


def test_worker_result_defaults():
    result = WorkerResult(worker_type="zone_synthesis")
    assert result.worker_type == "zone_synthesis"
    assert result.layers == []
    assert result.parcel_changes == []
    assert result.relations == []
    assert result.unresolved_items == []
    assert result.diagnostics == []
    assert result.provenance is None


def test_worker_result_accepts_items():
    result = WorkerResult(
        worker_type="zone_synthesis",
        layers=[{"type": "FeatureCollection"}],
        parcel_changes=[{"bsm": "P001"}],
        diagnostics=["ok"],
    )
    assert len(result.layers) == 1
    assert len(result.parcel_changes) == 1
    assert result.diagnostics == ["ok"]


def test_execution_plan_defaults_inherit_meta():
    plan = ExecutionPlan(plan_id="p1")
    assert plan.plan_id == "p1"
    assert plan.context_version == ""
    assert plan.worker_tasks == []
    assert plan.dependencies == []
    assert plan.provenance is None
    assert plan.intent is None
    assert plan.site_selection is None
    assert plan.land_design_briefs == []


def test_execution_plan_embeds_parse_and_select_contracts():
    intent = SpatialPlanningIntent(village_name="v1")
    ssd = SiteSelectionDecision(selected_combination=["P001"])
    brief = LandDesignBrief(project_ref="p1")
    task = WorkerTask(task_id="t1", worker_type=WorkerType.ZONE_SYNTHESIS)
    plan = ExecutionPlan(
        plan_id="p1",
        intent=intent,
        site_selection=ssd,
        land_design_briefs=[brief],
        worker_tasks=[task],
        context_version="v1",
    )
    assert plan.context_version == "v1"
    assert plan.intent.village_name == "v1"
    assert plan.site_selection.selected_combination == ["P001"]
    assert plan.land_design_briefs[0].project_ref == "p1"
    assert plan.worker_tasks[0].worker_type == WorkerType.ZONE_SYNTHESIS


def test_execution_result_defaults():
    result = ExecutionResult(task_id="t1")
    assert result.status == "pending"
    assert result.output_artifacts == []
    assert result.errors == []


def test_parcel_allocation_problem_defaults():
    problem = ParcelAllocationProblem()
    assert problem.targets == {}
    assert problem.candidates == {}
    assert problem.constraints == []
    assert problem.metadata == {}


def test_parcel_allocation_problem_roundtrip():
    problem = ParcelAllocationProblem(
        targets={"Z1": 1.5},
        candidates={"Z1": ["P001", "P002"]},
        constraints=[{"type": "preserve", "bsms": ["P999"]}],
        metadata={"zone": "village"},
    )
    assert problem.targets["Z1"] == 1.5
    assert problem.candidates["Z1"] == ["P001", "P002"]
    assert problem.constraints[0]["type"] == "preserve"
    assert problem.metadata["zone"] == "village"


def test_zone_assignment_entry_defaults():
    entry = ZoneAssignmentEntry(bsm="P001")
    assert entry.zone_id == ""
    assert entry.land_use == ""
    assert entry.area_ha == 0.0
    assert entry.source == "allocator"


def test_zone_allocation_solution_defaults():
    solution = ZoneAllocationSolution()
    assert solution.assignments == []
    assert solution.unassigned_bsms == []
    assert solution.objective_value == 0.0
    assert solution.feasible is False
    assert solution.diagnostics == []


def test_zone_allocation_solution_with_assignments():
    entry = ZoneAssignmentEntry(bsm="P001", zone_id="Z1", land_use="耕地", area_ha=1.0)
    solution = ZoneAllocationSolution(
        assignments=[entry],
        unassigned_bsms=["P002"],
        objective_value=1.0,
        feasible=True,
    )
    assert solution.assignments[0].zone_id == "Z1"
    assert solution.assignments[0].land_use == "耕地"
    assert solution.unassigned_bsms == ["P002"]
    assert solution.objective_value == 1.0
    assert solution.feasible is True


def test_road_plan_result_defaults():
    result = RoadPlanResult()
    assert result.layers == []
    assert result.road_plan is None
    assert result.road_network_changes == []
    assert result.connectivity_report == {}
    assert result.unresolved_items == []
    assert result.available is False


def test_road_plan_result_available():
    result = RoadPlanResult(
        layers=[{"type": "FeatureCollection"}],
        road_plan={"routes": []},
        connectivity_report={"connected": True},
        available=True,
    )
    assert result.available is True
    assert result.connectivity_report["connected"] is True
