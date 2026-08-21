from app.contracts.spatial.candidate_geometry import CandidateGeometry
from app.contracts.spatial.grounded_problem import (
    GroundedPlanningProblem,
    GroundedTargetDomain,
)
from app.contracts.workflow.execution_plan_contracts import (
    ExecutionPlan,
    WorkerTask,
    WorkerType,
)
from app.contracts.workflow.parse_contracts import SiteAreaTarget
from app.contracts.domain.selection_contracts import TargetAssignment
from app.domain.materialization.execute_state import ExecuteAgentState
from app.domain.materialization.nodes.project_worker import _project_worker
from app.domain.allocation.refined_candidate_catalog import build_refined_candidate_catalog
from app.domain.suitability.model import SuitabilityCandidate, SuitabilitySurface


def test_execute_keeps_selected_planning_subgeometry_instead_of_full_bsm(monkeypatch):
    target = SiteAreaTarget(
        target_id="project-1",
        site_area_id="project-1",
        name="大地块内的服务点建设用地",
        expected_output_kind="polygon",
        materialization_role="site_footprint",
    )
    candidate = CandidateGeometry(
        candidate_id="candidate:subgeometry-1",
        target_id="project-1",
        kind="polygon",
        role="execution_geometry",
        wkt="POLYGON ((0 0, 0.002 0, 0.002 0.002, 0 0.002, 0 0))",
        spatial_domain_kind="parcel_extent",
        source_bsms=["P-1"],
        source_area_ha=8.0,
        planning_area_ha=0.6,
        coverage_ratio=0.075,
        source_ref="bundle:landuse_current:P-1",
        evidence_refs=["l1:fact:project-1", "kg:entity:project-1"],
        bundle_snapshot_digest="bundle-1",
    )
    assignment = TargetAssignment(
        target_id="project-1",
        target_type="site_area",
        status="placed",
        selected_bsm="P-1",
        expected_output_kind="polygon",
        target_binding={
            **target.model_dump(mode="json"),
            "candidate_id": candidate.candidate_id,
        },
    )
    task = WorkerTask(
        task_id="site_area_footprint:project-1",
        worker_type=WorkerType.SITE_AREA_FOOTPRINT,
        target_id="project-1",
        target_type="site_area",
        expected_output_kind="polygon",
        assignment=assignment,
        candidate_id=candidate.candidate_id,
        target_binding=dict(assignment.target_binding),
    )
    state = ExecuteAgentState(
        execution_plan=ExecutionPlan(worker_tasks=[task]),
        candidate_geometry_by_id={candidate.candidate_id: candidate},
        land_design_briefs=[],
    )

    def must_not_expand_to_full_parcel(*args, **kwargs):
        raise AssertionError("full source BSM geometry was used instead of SELECT geometry")

    monkeypatch.setattr(
        "app.domain.materialization.land_design_worker.design_project_footprint",
        must_not_expand_to_full_parcel,
    )
    monkeypatch.setattr(
        "app.domain.materialization.nodes.project_worker._resolve_parcel_by_bsm",
        lambda _state: {"P-1": object()},
    )

    result = _project_worker(state)

    feature = result.layers[0]["data"]["features"][0]
    assert tuple(feature["geometry"]["coordinates"][0][1]) == (0.002, 0.0)
    assert feature["properties"]["source_bsms"] == ["P-1"]
    assert feature["properties"]["planning_area_ha"] == 0.6
    assert feature["properties"]["coverage_ratio"] == 0.075
    assert result.scenario_features[0].source_bsms == ["P-1"]


def test_execute_defers_non_executable_candidate_instead_of_expanding_bsm(monkeypatch):
    target = SiteAreaTarget(
        target_id="project-deferred",
        site_area_id="project-deferred",
        name="需要补证据的局部地块",
        expected_output_kind="polygon",
        materialization_role="site_footprint",
    )
    candidate = CandidateGeometry(
        target_id="project-deferred",
        kind="polygon",
        role="parcel_candidate",
        wkt="POLYGON ((0 0, 0.02 0, 0.02 0.02, 0 0.02, 0 0))",
        source_bsms=["P-2"],
        source_area_ha=80.0,
        planning_area_ha=0.0,
        coverage_ratio=0.0,
        subgeometry_operation="planning_clip_failed",
        subgeometry_diagnostics=["planning_area_insufficient"],
    )
    assignment = TargetAssignment(
        target_id="project-deferred",
        target_type="site_area",
        status="placed",
        selected_bsm="P-2",
        expected_output_kind="polygon",
        target_binding={**target.model_dump(mode="json"), "candidate_id": candidate.candidate_id},
    )
    task = WorkerTask(
        task_id="site_area_footprint:project-deferred",
        worker_type=WorkerType.SITE_AREA_FOOTPRINT,
        target_id="project-deferred",
        target_type="site_area",
        expected_output_kind="polygon",
        assignment=assignment,
        candidate_id=candidate.candidate_id,
        target_binding=dict(assignment.target_binding),
    )
    state = ExecuteAgentState(
        execution_plan=ExecutionPlan(worker_tasks=[task]),
        candidate_geometry_by_id={candidate.candidate_id: candidate},
        land_design_briefs=[],
    )
    monkeypatch.setattr(
        "app.domain.materialization.land_design_worker.design_project_footprint",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("non-executable candidate expanded to source BSM")
        ),
    )
    monkeypatch.setattr(
        "app.domain.materialization.nodes.project_worker._resolve_parcel_by_bsm",
        lambda _state: {"P-2": object()},
    )

    result = _project_worker(state)

    assert result.layers == []
    task_result = result.task_results[0]
    assert task_result.status == "deferred"
    assert task_result.diagnostics[0]["code"] == "candidate_geometry_not_executable"
    assert task_result.diagnostics[0]["subgeometry_diagnostics"] == [
        "planning_area_insufficient"
    ]


def test_select_promotes_planning_area_and_coverage_ratio():
    source = CandidateGeometry(
        target_id="project-1",
        kind="polygon",
        role="parcel_candidate",
        wkt="POLYGON ((0 0, 0.02 0, 0.02 0.02, 0 0.02, 0 0))",
        spatial_domain_kind="parcel_extent",
        source_bsms=["P-1"],
        source_area_ha=8.0,
    )
    problem = GroundedPlanningProblem(
        target_domains=[
            GroundedTargetDomain(
                target_id="project-1",
                target_kind="site_area",
                expected_output_kind="polygon",
            )
        ],
        candidate_geometries=[source],
    )
    surface = SuitabilitySurface(
        candidates=[
            SuitabilityCandidate(
                candidate_id="surface:P-1",
                target_id="project-1",
                source_parcels=["P-1"],
                hard_feasible=True,
                available_geometry_wkt=(
                    "POLYGON ((0 0, 0.002 0, 0.002 0.002, 0 0.002, 0 0))"
                ),
                available_area_ha=0.6,
            )
        ]
    )

    refined = build_refined_candidate_catalog(problem, surface)
    selected = next(item for item in refined.values() if item.generation_operation == "select_parcel_refinement")

    assert selected.role == "execution_geometry"
    assert selected.source_area_ha == 8.0
    assert selected.planning_area_ha == 0.6
    assert selected.coverage_ratio == 0.075
    assert selected.source_bsms == ["P-1"]
