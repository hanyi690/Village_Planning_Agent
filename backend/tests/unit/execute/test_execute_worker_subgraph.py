"""EXECUTE multi-worker subgraph (Wave O): topology, workers, merge, allocator port.

Verifies the new EXECUTE graph compiles with the 5 workers + merge +
materialize + planned_state_builder + execution_review, that each worker
returns a WorkerResult, that zone_worker drives the ZoneAllocatorPort for
empty-candidate zones (feasible + infeasible), that facility_worker activates
the containing-parcel branch, and that merge_worker_results detects BSM
conflicts. All I/O is mocked - no real LLM, DB, or network.
"""

import asyncio
from types import SimpleNamespace

from app.agent.execute.execute_agent import (
    _project_worker,
    _zone_worker,
    build_execute_agent_graph,
)
from app.agent.execute.execute_state import ExecuteAgentState
from app.agent.execute.merge import merge_worker_results
from app.modules.schema.contracts.execution_plan_contracts import (
    WorkerResult,
    ZoneAllocationSolution,
    ZoneAssignmentEntry,
)
from app.modules.schema.contracts.parse_contracts import (
    FacilityTarget,
    ProjectTarget,
    SpatialPlanningIntent,
    ZoneTarget,
)
from app.modules.schema.contracts.selection_contracts import (
    LandDesignBrief,
    SiteSelectionDecision,
)

_EXPECTED_NODES = {
    "route_tasks",
    "prepare_inputs",
    "project_worker",
    "zone_worker",
    "facility_worker",
    "axis_worker",
    "road_worker",
    "merge_worker_results",
    "geometry_materialize",
    "planned_state_builder",
    "execution_review",
}


def _landuse(*bsms):
    features = []
    for bsm in bsms:
        features.append({
            "type": "Feature",
            "properties": {"BSM": bsm, "DLBM": "0101", "area_sqm": 10000},
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[116.0, 24.8], [116.1, 24.8], [116.1, 24.9], [116.0, 24.9], [116.0, 24.8]]],
            },
        })
    return {"type": "FeatureCollection", "features": features}


def _zone(bsms=None, area_ha=1.0, land_use="Z1"):
    return ZoneTarget(
        land_use=land_use, planning_zone=land_use,
        area_ha=area_ha, candidate_bsms=list(bsms or []),
    )


def _project():
    return ProjectTarget(
        project_id="p1", name="P1", scale_text="1.5公顷", candidate_bsms=["P001"]
    )


def _state(**overrides):
    defaults = dict(
        session_id="s1",
        tasks_to_run=["layout", "project", "facility"],
        gis_data={"landuse_current_geojson": _landuse("P001", "P002")},
    )
    defaults.update(overrides)
    return ExecuteAgentState(**defaults)


# ── Topology ─────────────────────────────────────────────────────────


def test_graph_compiles_with_multi_worker_topology():
    graph = build_execute_agent_graph()
    nodes = set(graph.get_graph().nodes.keys())
    assert _EXPECTED_NODES.issubset(nodes)


def test_graph_runs_full_pipeline_mocked():
    intent = SpatialPlanningIntent(
        zone_targets=[_zone(bsms=["P002"])],
        project_targets=[_project()],
        facilities=[FacilityTarget(type="school", anchor_point=(0.01, 0.01))],
    )
    ssd = SiteSelectionDecision(selected_combination=["P001"])
    briefs = [LandDesignBrief(project_ref="p1")]

    exec_state = _state()
    exec_dict = exec_state.model_dump()
    exec_dict["session_id"] = ""  # skip route_tasks KG validation (no real KG in unit test)
    exec_dict["intent"] = intent
    exec_dict["site_selection"] = ssd
    exec_dict["land_design_briefs"] = briefs

    graph = build_execute_agent_graph()
    result = asyncio.run(graph.ainvoke(exec_dict))

    assert result["parcel_changeset"] is not None
    assert result["parcel_changeset"].changes
    assert result["layout_configs"]
    assert result["planned_state"] is not None
    assert result["validation_result"]["passed"] is True
    worker_types = {r.worker_type for r in result["worker_results"]}
    assert {"project", "zone", "facility"}.issubset(worker_types)


def test_parallel_fanout_runs_both_facility_and_axis():
    from app.modules.schema.contracts.parse_contracts import AxisTarget

    intent = SpatialPlanningIntent(
        zone_targets=[_zone(bsms=["P002"])],
        facilities=[FacilityTarget(type="school", anchor_point=(0.01, 0.01))],
        development_axes=[AxisTarget(label="main", reference_feature="road")],
    )
    exec_state = _state()
    exec_dict = exec_state.model_dump()
    exec_dict["session_id"] = ""
    exec_dict["intent"] = intent

    graph = build_execute_agent_graph()
    result = asyncio.run(graph.ainvoke(exec_dict))

    worker_types = {r.worker_type for r in result["worker_results"]}
    assert {"facility", "axis"}.issubset(worker_types)
    assert result["validation_result"]["passed"] is True
    assert any(
        (c.get("layerType") or c.get("layer_type")) == "facility_point"
        for c in result["layout_configs"]
    )
    assert any(
        (c.get("layerType") or c.get("layer_type")) == "infrastructure"
        for c in result["layout_configs"]
    )


# ── project_worker ───────────────────────────────────────────────────


def test_project_worker_returns_worker_result_with_changes():
    state = _state(
        intent=SpatialPlanningIntent(project_targets=[_project()]),
        site_selection=SiteSelectionDecision(selected_combination=["P001"]),
        land_design_briefs=[LandDesignBrief(project_ref="p1")],
        tasks_to_run=["project"],
    )

    result = _project_worker(state)

    assert isinstance(result, WorkerResult)
    assert result.worker_type == "project"
    assert result.parcel_changes
    assert any(layer["layerType"] == "planned_project" for layer in result.layers)


# ── zone_worker + ZoneAllocatorPort ─────────────────────────────────


class _MockAllocator:
    def __init__(self, solution):
        self.solution = solution
        self.calls = []

    def allocate(self, targets, candidates, constraints=None, metadata=None):
        self.calls.append((dict(targets), dict(candidates), constraints, metadata))
        return self.solution


def _empty_candidate_state(allocator):
    return _state(
        tasks_to_run=["layout"],
        intent=SpatialPlanningIntent(
            zone_targets=[_zone(bsms=[], area_ha=1.0, land_use="Z1")]
        ),
        ports=SimpleNamespace(zone_allocator=allocator),
    )


def test_zone_worker_uses_allocator_for_empty_candidates():
    solution = ZoneAllocationSolution(
        assignments=[ZoneAssignmentEntry(bsm="P001", zone_id="Z1", area_ha=1.0)],
        feasible=True,
        diagnostics=["Assigned 1 parcels"],
    )
    allocator = _MockAllocator(solution)
    state = _empty_candidate_state(allocator)

    result = _zone_worker(state)

    assert allocator.calls, "allocator.allocate was not invoked"
    targets, candidates, _constraints, metadata = allocator.calls[0]
    assert targets == {"Z1": 1.0}
    assert set(candidates["Z1"]) == {"P001", "P002"}
    assert metadata.get("parcel_by_bsm")
    assert isinstance(result, WorkerResult)
    assert result.worker_type == "zone"
    assert result.parcel_changes
    assert all(c.action == "reclassify" for c in result.parcel_changes)


def test_zone_worker_infeasible_allocation_unresolved():
    solution = ZoneAllocationSolution(
        feasible=False,
        diagnostics=["Solver status: Infeasible"],
    )
    allocator = _MockAllocator(solution)
    state = _empty_candidate_state(allocator)

    result = _zone_worker(state)

    assert result.parcel_changes == []
    codes = [item["code"] for item in result.unresolved_items]
    assert "design_unresolved" in codes
    item = next(i for i in result.unresolved_items if i["code"] == "design_unresolved")
    assert item["kind"] == "zone_allocation_infeasible"


# ── facility_worker containing-parcel branch ─────────────────────────


def test_facility_worker_passes_real_parcel_by_bsm():
    from app.agent.execute.execute_agent import _facility_worker

    state = ExecuteAgentState(
        tasks_to_run=["facility"],
        gis_data={
            "landuse_current_geojson": {
                "type": "FeatureCollection",
                "features": [{
                    "type": "Feature",
                    "properties": {"BSM": "P001", "DLBM": "0701", "area_sqm": 12000},
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [[[0.0, 0.0], [0.001, 0.0], [0.001, 0.001], [0.0, 0.001], [0.0, 0.0]]],
                    },
                }],
            }
        },
        intent=SpatialPlanningIntent(
            facilities=[FacilityTarget(type="school", anchor_point=(0.0005, 0.0005))]
        ),
    )

    result = _facility_worker(state)

    assert isinstance(result, WorkerResult)
    assert result.parcel_changes
    assert result.parcel_changes[0].action == "reclassify"
    assert result.parcel_changes[0].derived_from_bsms == ["P001"]


# ── merge_worker_results BSM conflict detection ──────────────────────


def _classification(code):
    from app.modules.schema.contracts.classification_ref import ClassificationRef

    return ClassificationRef(system="ghytbm", code=code, canonical_name=code, source="derived")


def _change(bsm, action, code):
    from app.modules.schema.contracts.parcel_change_contracts import ParcelChange

    return ParcelChange(
        bsm=bsm,
        action=action,
        derived_from_bsms=[bsm],
        after_classification=_classification(code),
        after_geometry_wkt="POLYGON ((0 0, 0 1, 1 1, 1 0, 0 0))",
        new_area_ha=1.0,
    )


def test_merge_worker_results_detects_bsm_conflict():
    project = WorkerResult(
        worker_type="project",
        parcel_changes=[_change("P001", "reclassify", "0701")],
    )
    zone = WorkerResult(
        worker_type="zone",
        parcel_changes=[_change("P001", "reclassify", "0301")],
    )

    changeset, layouts, diagnostics = merge_worker_results([project, zone])

    conflicts = [d for d in diagnostics if d["type"] == "bsm_conflict"]
    assert len(conflicts) == 1
    assert conflicts[0]["bsm"] == "P001"
    workers = {w["worker_type"]: w["after_code"] for w in conflicts[0]["workers"]}
    assert workers == {"project": "0701", "zone": "0301"}


def test_merge_worker_results_no_conflict_when_same_code():
    a = WorkerResult(
        worker_type="project",
        parcel_changes=[_change("P001", "reclassify", "0701")],
    )
    b = WorkerResult(
        worker_type="facility",
        parcel_changes=[_change("P002", "create", "0701")],
    )

    changeset, layouts, diagnostics = merge_worker_results([a, b])

    assert changeset is not None
    assert len(changeset.changes) == 2
    assert all(d["type"] != "bsm_conflict" for d in diagnostics)
