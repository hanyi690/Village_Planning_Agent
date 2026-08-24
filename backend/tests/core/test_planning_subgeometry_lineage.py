from types import SimpleNamespace

import pytest

from app.contracts.artifacts.classification_ref import ClassificationDecision
from app.contracts.spatial.candidate_geometry import CandidateGeometry
from app.contracts.spatial.parcel_change_contracts import ParcelChange
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
from app.contracts.workflow.materialization_contracts import LandDesignBrief, TargetAssignment
from app.domain.materialization.execute_state import ExecuteAgentState
from app.domain.materialization.nodes.project_worker import (
    _candidate_site_footprint_changes,
    _project_worker,
    _shared_parcel_remainder_changes,
)
from app.domain.allocation.refined_candidate_catalog import build_refined_candidate_catalog
from app.domain.suitability.model import SuitabilityCandidate, SuitabilitySurface


def test_execute_rejects_partial_footprint_outside_frozen_eligible_extent():
    project = SimpleNamespace(
        target_id="project-partial-boundary",
        materialization_role="site_footprint",
        classification_decision=ClassificationDecision(
            target_id="project-partial-boundary",
            code_system="ghytbm",
            candidate_codes=["2124"],
            selected_code="2124",
            decision_mode="rule",
            evidence_refs=["claim:project-partial-boundary"],
            status="resolved",
        ),
    )
    candidate = CandidateGeometry(
        candidate_id="candidate:partial-boundary",
        target_id=project.target_id,
        kind="polygon",
        role="execution_geometry",
        wkt="POLYGON ((0.008 0, 0.01 0, 0.01 0.01, 0.008 0.01, 0.008 0))",
        eligible_geometry_wkt="POLYGON ((0 0, 0.007 0, 0.007 0.01, 0 0.01, 0 0))",
        spatial_domain_kind="parcel_extent",
        source_bsms=["P-PARTIAL-BOUNDARY"],
        source_area_ha=8.0,
        planning_area_ha=0.2,
        availability_status="partially_available",
        eligible_area_ha=5.6,
        excluded_area_ha=2.4,
    )
    parcel = SimpleNamespace(
        bsm="P-PARTIAL-BOUNDARY",
        geometry={
            "type": "Polygon",
            "coordinates": [[[0, 0], [0.01, 0], [0.01, 0.01], [0, 0.01], [0, 0]]],
        },
    )

    assert _candidate_site_footprint_changes(
        project,
        candidate,
        {parcel.bsm: parcel},
    ) == []


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
        availability_status="partially_available",
        eligible_area_ha=6.5,
        excluded_area_ha=1.5,
        adjacent_parcel_bsms=["P-2"],
        adjacency_evidence_refs=["bundle:landuse_current:P-1:adjacent:P-2"],
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
    assert feature["properties"]["availability_status"] == "partially_available"
    assert feature["properties"]["adjacent_parcel_bsms"] == ["P-2"]
    assert result.scenario_features[0].source_bsms == ["P-1"]
    assert result.scenario_features[0].availability_status == "partially_available"
    assert result.scenario_features[0].adjacent_parcel_bsms == ["P-2"]


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


def test_execute_does_not_treat_unknown_source_parcel_as_fully_available():
    target = SiteAreaTarget(
        target_id="project-unknown-availability",
        site_area_id="project-unknown-availability",
        name="可用性未闭合的源地块",
        expected_output_kind="polygon",
        materialization_role="site_footprint",
        classification_decision=ClassificationDecision(
            target_id="project-unknown-availability",
            code_system="ghytbm",
            candidate_codes=["2124"],
            selected_code="2124",
            decision_mode="rule",
            evidence_refs=["claim:project-unknown-availability"],
            status="resolved",
        ),
    )
    candidate = CandidateGeometry(
        target_id=target.target_id,
        kind="polygon",
        role="execution_geometry",
        materialization_role="site_footprint",
        wkt="POLYGON ((0 0, 0.005 0, 0.005 0.01, 0 0.01, 0 0))",
        spatial_domain_kind="parcel_extent",
        source_bsms=["P-UNKNOWN"],
        source_area_ha=1.0,
        planning_area_ha=0.2,
        availability_status="unknown",
        evidence_refs=["claim:project-unknown-availability"],
    )
    assignment = TargetAssignment(
        target_id=target.target_id,
        target_type="site_area",
        status="placed",
        selected_bsm="P-UNKNOWN",
        expected_output_kind="polygon",
        target_binding={
            **target.model_dump(mode="json"),
            "candidate_id": candidate.candidate_id,
        },
    )
    task = WorkerTask(
        task_id="site_area_footprint:project-unknown-availability",
        worker_type=WorkerType.SITE_AREA_FOOTPRINT,
        target_id=target.target_id,
        target_type="site_area",
        expected_output_kind="polygon",
        assignment=assignment,
        candidate_id=candidate.candidate_id,
        target_binding=dict(assignment.target_binding),
    )
    state = ExecuteAgentState(
        execution_plan=ExecutionPlan(worker_tasks=[task]),
        candidate_geometry_by_id={candidate.candidate_id: candidate},
        parcel_by_bsm={"P-UNKNOWN": SimpleNamespace(
            bsm="P-UNKNOWN",
            geometry={
                "type": "Polygon",
                "coordinates": [[[0, 0], [0.01, 0], [0.01, 0.01], [0, 0.01], [0, 0]]],
            },
            area_sqm=10_000.0,
            dlbm="0101",
            dlbm_system="gbt21010",
        )},
    )

    result = _project_worker(state)

    assert result.parcel_changes == []
    assert result.layers == []
    assert result.task_results[0].status == "deferred"
    assert result.task_results[0].diagnostics[0]["code"] == (
        "candidate_geometry_not_executable"
    )


def test_execute_materializes_site_footprint_as_parcel_change(monkeypatch):
    target = SiteAreaTarget(
        target_id="project-footprint",
        site_area_id="project-footprint",
        name="可落地建设用地",
        expected_output_kind="polygon",
        materialization_role="site_footprint",
        classification_decision=ClassificationDecision(
            target_id="project-footprint",
            code_system="ghytbm",
            candidate_codes=["2124"],
            selected_code="2124",
            decision_mode="rule",
            evidence_refs=["claim:project-footprint"],
            status="resolved",
        ),
    )
    candidate = CandidateGeometry(
        candidate_id="candidate:footprint-1",
        target_id="project-footprint",
        kind="polygon",
        role="execution_geometry",
        materialization_role="site_footprint",
        wkt="POLYGON ((0 0, 0.005 0, 0.005 0.01, 0 0.01, 0 0))",
        spatial_domain_kind="parcel_extent",
        source_bsms=["P-1"],
        source_area_ha=8.0,
        planning_area_ha=0.6,
        coverage_ratio=0.075,
        availability_status="partially_available",
        eligible_area_ha=6.5,
        excluded_area_ha=1.5,
        adjacent_parcel_bsms=["P-2"],
        adjacency_evidence_refs=["bundle:landuse_current:P-1:adjacent:P-2"],
        evidence_refs=["claim:project-footprint"],
    )
    assignment = TargetAssignment(
        target_id="project-footprint",
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
        task_id="site_area_footprint:project-footprint",
        worker_type=WorkerType.SITE_AREA_FOOTPRINT,
        target_id="project-footprint",
        target_type="site_area",
        expected_output_kind="polygon",
        assignment=assignment,
        candidate_id=candidate.candidate_id,
        target_binding=dict(assignment.target_binding),
    )
    parcel = SimpleNamespace(
        bsm="P-1",
        geometry={
            "type": "Polygon",
            "coordinates": [[[0, 0], [0.01, 0], [0.01, 0.01], [0, 0.01], [0, 0]]],
        },
        area_sqm=80_000.0,
        dlbm="0101",
        dlbm_system="gbt21010",
    )
    state = ExecuteAgentState(
        execution_plan=ExecutionPlan(worker_tasks=[task]),
        candidate_geometry_by_id={candidate.candidate_id: candidate},
        parcel_by_bsm={"P-1": parcel},
        land_design_briefs=[],
    )

    result = _project_worker(state)

    assert [change.action for change in result.parcel_changes] == ["create", "preserve"]
    assert result.parcel_changes[0].new_area_ha == 0.6
    assert result.parcel_changes[0].derived_from_bsms == ["P-1"]
    assert result.parcel_changes[0].availability_status == "partially_available"
    assert result.parcel_changes[0].eligible_area_ha == 6.5
    assert result.parcel_changes[0].excluded_area_ha == 1.5
    assert result.parcel_changes[0].adjacent_parcel_bsms == ["P-2"]
    assert result.task_results[0].status == "succeeded"
    feature = result.layers[0]["data"]["features"][0]
    assert feature["properties"]["parcel_change_materialized"] is True


def test_execute_defers_explicit_adjacency_requirement_without_evidence(monkeypatch):
    target = SiteAreaTarget(
        target_id="project-adj-required",
        site_area_id="project-adj-required",
        name="需联系周边地块的项目",
        expected_output_kind="polygon",
        materialization_role="site_footprint",
        classification_decision=ClassificationDecision(
            target_id="project-adj-required",
            code_system="ghytbm",
            candidate_codes=["2124"],
            selected_code="2124",
            decision_mode="rule",
            evidence_refs=["claim:project-adj-required"],
            status="resolved",
        ),
    )
    candidate = CandidateGeometry(
        candidate_id="candidate:adj-required",
        target_id=target.target_id,
        kind="polygon",
        role="execution_geometry",
        materialization_role="site_footprint",
        wkt="POLYGON ((0 0, 0.005 0, 0.005 0.01, 0 0.01, 0 0))",
        spatial_domain_kind="parcel_extent",
        source_bsms=["P-ADJ"],
        source_area_ha=8.0,
        planning_area_ha=0.6,
        availability_status="partially_available",
        eligible_area_ha=6.5,
        excluded_area_ha=1.5,
    )
    assignment = TargetAssignment(
        target_id=target.target_id,
        target_type="site_area",
        status="placed",
        selected_bsm="P-ADJ",
        expected_output_kind="polygon",
        target_binding={**target.model_dump(mode="json"), "candidate_id": candidate.candidate_id},
    )
    task = WorkerTask(
        task_id="site_area_footprint:project-adj-required",
        worker_type=WorkerType.SITE_AREA_FOOTPRINT,
        target_id=target.target_id,
        target_type="site_area",
        expected_output_kind="polygon",
        assignment=assignment,
        candidate_id=candidate.candidate_id,
        target_binding=dict(assignment.target_binding),
    )
    state = ExecuteAgentState(
        execution_plan=ExecutionPlan(worker_tasks=[task]),
        candidate_geometry_by_id={candidate.candidate_id: candidate},
        parcel_by_bsm={"P-ADJ": SimpleNamespace(
            bsm="P-ADJ",
            geometry={
                "type": "Polygon",
                "coordinates": [[[0, 0], [0.01, 0], [0.01, 0.01], [0, 0.01], [0, 0]]],
            },
            area_sqm=80_000.0,
            dlbm="0101",
            dlbm_system="gbt21010",
        )},
        land_design_briefs=[LandDesignBrief(
            project_ref=target.target_id,
            adjacency_requirements=["must coordinate with neighboring parcel"],
        )],
    )

    result = _project_worker(state)

    assert result.parcel_changes == []
    assert result.task_results[0].status == "failed"
    assert result.task_results[0].diagnostics[0]["code"] == (
        "approved_site_footprint_adjacency_evidence_missing"
    )


def test_execute_keeps_adjacent_parcel_as_context_without_mutating_neighbor(monkeypatch):
    target = SiteAreaTarget(
        target_id="project-adj-context",
        site_area_id="project-adj-context",
        name="需要与邻地协调但不合并",
        expected_output_kind="polygon",
        materialization_role="site_footprint",
        classification_decision=ClassificationDecision(
            target_id="project-adj-context",
            code_system="ghytbm",
            candidate_codes=["2124"],
            selected_code="2124",
            decision_mode="rule",
            evidence_refs=["claim:project-adj-context"],
            status="resolved",
        ),
    )
    candidate = CandidateGeometry(
        candidate_id="candidate:adj-context",
        target_id=target.target_id,
        kind="polygon",
        role="execution_geometry",
        materialization_role="site_footprint",
        wkt="POLYGON ((0 0, 0.005 0, 0.005 0.01, 0 0.01, 0 0))",
        spatial_domain_kind="parcel_extent",
        source_bsms=["P-ADJ-CONTEXT"],
        source_area_ha=8.0,
        planning_area_ha=0.6,
        availability_status="partially_available",
        eligible_area_ha=6.5,
        excluded_area_ha=1.5,
        adjacent_parcel_bsms=["P-NEIGHBOR"],
        adjacency_evidence_refs=[
            "bundle:landuse_current:P-ADJ-CONTEXT:adjacent:P-NEIGHBOR"
        ],
        relation_refs=["relation:adjacent:project-adj-context:P-NEIGHBOR"],
    )
    assignment = TargetAssignment(
        target_id=target.target_id,
        target_type="site_area",
        status="placed",
        selected_bsm="P-ADJ-CONTEXT",
        expected_output_kind="polygon",
        target_binding={**target.model_dump(mode="json"), "candidate_id": candidate.candidate_id},
    )
    task = WorkerTask(
        task_id="site_area_footprint:project-adj-context",
        worker_type=WorkerType.SITE_AREA_FOOTPRINT,
        target_id=target.target_id,
        target_type="site_area",
        expected_output_kind="polygon",
        assignment=assignment,
        candidate_id=candidate.candidate_id,
        target_binding=dict(assignment.target_binding),
    )
    parcel = SimpleNamespace(
        bsm="P-ADJ-CONTEXT",
        geometry={
            "type": "Polygon",
            "coordinates": [[[0, 0], [0.01, 0], [0.01, 0.01], [0, 0.01], [0, 0]]],
        },
        area_sqm=80_000.0,
        dlbm="0101",
        dlbm_system="gbt21010",
    )
    neighbor = SimpleNamespace(
        bsm="P-NEIGHBOR",
        geometry={
            "type": "Polygon",
            "coordinates": [[[0.01, 0], [0.02, 0], [0.02, 0.01], [0.01, 0.01], [0.01, 0]]],
        },
        area_sqm=80_000.0,
        dlbm="0101",
        dlbm_system="gbt21010",
    )
    state = ExecuteAgentState(
        execution_plan=ExecutionPlan(worker_tasks=[task]),
        candidate_geometry_by_id={candidate.candidate_id: candidate},
        parcel_by_bsm={parcel.bsm: parcel, neighbor.bsm: neighbor},
        land_design_briefs=[
            LandDesignBrief(
                project_ref=target.target_id,
                adjacency_requirements=["must coordinate with neighboring parcel"],
            )
        ],
    )

    result = _project_worker(state)

    assert [change.bsm for change in result.parcel_changes] == [
        "project-adj-context:footprint",
        "project-adj-context:remainder",
    ]
    assert all("P-NEIGHBOR" not in change.derived_from_bsms for change in result.parcel_changes)
    assert result.parcel_changes[0].relation_refs == [
        "relation:adjacent:project-adj-context:P-NEIGHBOR"
    ]
    assert result.task_results[0].status == "succeeded"


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


def test_select_normalizes_fully_unavailable_recall_geometry_to_zero_planning_area():
    source = CandidateGeometry(
        target_id="project-unavailable",
        kind="polygon",
        role="parcel_candidate",
        wkt="POLYGON ((0 0, 0.02 0, 0.02 0.02, 0 0.02, 0 0))",
        spatial_domain_kind="parcel_extent",
        source_bsms=["P-UNAVAILABLE"],
        source_area_ha=1.0,
    )
    problem = GroundedPlanningProblem(
        target_domains=[
            GroundedTargetDomain(
                target_id="project-unavailable",
                target_kind="site_area",
                expected_output_kind="polygon",
            )
        ],
        candidate_geometries=[source],
    )
    surface = SuitabilitySurface(
        candidates=[
            SuitabilityCandidate(
                candidate_id="surface:P-UNAVAILABLE",
                target_id="project-unavailable",
                source_parcels=["P-UNAVAILABLE"],
                hard_feasible=False,
                exclusion_reasons=["FARMLAND_PROTECTION"],
                available_geometry_wkt=source.wkt,
                available_area_ha=1.0,
                source_area_ha=1.0,
                coverage_ratio=1.0,
                availability_status="fully_unavailable",
                eligible_area_ha=0.0,
                excluded_area_ha=1.0,
            )
        ]
    )

    refined = build_refined_candidate_catalog(problem, surface)
    selected = next(
        item
        for item in refined.values()
        if item.source_bsms == ["P-UNAVAILABLE"]
        and item.generation_operation == "select_parcel_refinement"
    )

    assert selected.availability_status == "fully_unavailable"
    assert selected.planning_area_ha == 0.0
    assert selected.coverage_ratio == 0.0
    assert selected.eligible_area_ha == 0.0
    assert selected.excluded_area_ha == 1.0
    assert selected.is_executable is False


def test_select_uses_exact_suitability_source_area_for_availability_partition():
    source = CandidateGeometry(
        target_id="project-area-authority",
        kind="polygon",
        role="parcel_candidate",
        wkt="POLYGON ((0 0, 0.02 0, 0.02 0.02, 0 0.02, 0 0))",
        spatial_domain_kind="parcel_extent",
        source_bsms=["P-AREA"],
        # Coarse GROUND extent; the exact BSM measurement is supplied by
        # Suitability below.
        source_area_ha=0.075,
    )
    problem = GroundedPlanningProblem(
        target_domains=[
            GroundedTargetDomain(
                target_id="project-area-authority",
                target_kind="site_area",
                expected_output_kind="polygon",
            )
        ],
        candidate_geometries=[source],
    )
    surface = SuitabilitySurface(
        candidates=[
            SuitabilityCandidate(
                candidate_id="surface:P-AREA",
                target_id="project-area-authority",
                source_parcels=["P-AREA"],
                hard_feasible=True,
                available_geometry_wkt=(
                    "POLYGON ((0 0, 0.002 0, 0.002 0.002, 0 0.002, 0 0))"
                ),
                available_area_ha=0.076,
                source_area_ha=0.076,
                coverage_ratio=1.0,
                availability_status="partially_available",
                eligible_area_ha=0.076,
                excluded_area_ha=0.0,
            )
        ]
    )

    refined = build_refined_candidate_catalog(problem, surface)
    selected = next(
        item
        for item in refined.values()
        if item.generation_operation == "select_parcel_refinement"
    )

    assert selected.source_area_ha == 0.076
    assert selected.eligible_area_ha == 0.076
    assert selected.excluded_area_ha == 0.0
    assert selected.coverage_ratio == 1.0


def test_select_clamps_rounding_residue_for_fully_available_candidate():
    source = CandidateGeometry(
        target_id="project-full-rounding",
        kind="polygon",
        role="parcel_candidate",
        wkt="POLYGON ((0 0, 0.02 0, 0.02 0.02, 0 0.02, 0 0))",
        spatial_domain_kind="parcel_extent",
        source_bsms=["P-FULL-ROUNDING"],
        source_area_ha=1.0,
    )
    problem = GroundedPlanningProblem(
        target_domains=[
            GroundedTargetDomain(
                target_id="project-full-rounding",
                target_kind="site_area",
                expected_output_kind="polygon",
            )
        ],
        candidate_geometries=[source],
    )
    surface = SuitabilitySurface(
        candidates=[
            SuitabilityCandidate(
                candidate_id="surface:P-FULL-ROUNDING",
                target_id="project-full-rounding",
                source_parcels=["P-FULL-ROUNDING"],
                hard_feasible=True,
                available_geometry_wkt=(
                    "POLYGON ((0 0, 0.002 0, 0.002 0.002, 0 0.002, 0 0))"
                ),
                available_area_ha=0.2,
                source_area_ha=1.0,
                coverage_ratio=0.2,
                availability_status="fully_available",
                eligible_area_ha=0.9999999,
                excluded_area_ha=0.0000001,
            )
        ]
    )

    refined = build_refined_candidate_catalog(problem, surface)
    selected = next(
        item
        for item in refined.values()
        if item.generation_operation == "select_parcel_refinement"
    )

    assert selected.availability_status == "fully_available"
    assert selected.excluded_area_ha == 0.0
    assert selected.is_executable is True


def test_select_does_not_hide_material_full_vs_excluded_conflict():
    source = CandidateGeometry(
        target_id="project-full-conflict",
        kind="polygon",
        role="parcel_candidate",
        wkt="POLYGON ((0 0, 0.02 0, 0.02 0.02, 0 0.02, 0 0))",
        spatial_domain_kind="parcel_extent",
        source_bsms=["P-FULL-CONFLICT"],
        source_area_ha=1.0,
    )
    problem = GroundedPlanningProblem(
        target_domains=[
            GroundedTargetDomain(
                target_id="project-full-conflict",
                target_kind="site_area",
                expected_output_kind="polygon",
            )
        ],
        candidate_geometries=[source],
    )
    surface = SuitabilitySurface(
        candidates=[
            SuitabilityCandidate(
                candidate_id="surface:P-FULL-CONFLICT",
                target_id="project-full-conflict",
                source_parcels=["P-FULL-CONFLICT"],
                hard_feasible=True,
                available_geometry_wkt=source.wkt,
                available_area_ha=0.8,
                source_area_ha=1.0,
                coverage_ratio=0.8,
                availability_status="fully_available",
                eligible_area_ha=0.8,
                excluded_area_ha=0.2,
            )
        ]
    )

    refined = build_refined_candidate_catalog(problem, surface)
    selected = next(
        item
        for item in refined.values()
        if item.generation_operation == "select_parcel_refinement"
    )

    assert selected.availability_status == "unknown"
    assert selected.excluded_area_ha == pytest.approx(0.2)
    assert selected.is_executable is False


def test_execute_catalog_reuses_persisted_partitioned_candidate_geometry():
    source = CandidateGeometry(
        target_id="shared-target",
        kind="polygon",
        role="parcel_candidate",
        wkt="POLYGON ((0 0, 0.02 0, 0.02 0.02, 0 0.02, 0 0))",
        spatial_domain_kind="parcel_extent",
        source_bsms=["P-SHARED"],
        source_area_ha=1.0,
    )
    problem = GroundedPlanningProblem(
        target_domains=[
            GroundedTargetDomain(
                target_id="shared-target",
                target_kind="site_area",
                expected_output_kind="polygon",
            )
        ],
        candidate_geometries=[source],
    )
    surface = SuitabilitySurface(
        candidates=[
            SuitabilityCandidate(
                candidate_id="surface:P-SHARED",
                target_id="shared-target",
                source_parcels=["P-SHARED"],
                hard_feasible=True,
                available_geometry_wkt=(
                    "POLYGON ((0 0, 0.01 0, 0.01 0.02, 0 0.02, 0 0))"
                ),
                available_area_ha=0.2,
                source_area_ha=1.0,
                eligible_area_ha=0.2,
                excluded_area_ha=0.8,
                availability_status="partially_available",
            )
        ]
    )
    initial = build_refined_candidate_catalog(problem, surface)
    refined = next(
        item
        for item in initial.values()
        if item.generation_operation == "select_parcel_refinement"
    )
    partitioned_wkt = "POLYGON ((0 0, 0.004 0, 0.004 0.02, 0 0.02, 0 0))"
    persisted = refined.model_copy(update={
        "wkt": partitioned_wkt,
        "candidate_bbox": (0.0, 0.0, 0.004, 0.02),
        "subgeometry_operation": "shared_parcel_capacity_partition",
    })
    persisted_problem = problem.model_copy(update={
        "candidate_geometries": [source, persisted],
    })

    rebuilt = build_refined_candidate_catalog(persisted_problem, surface)

    assert rebuilt[persisted.candidate_id].wkt == partitioned_wkt
    assert (
        rebuilt[persisted.candidate_id].subgeometry_operation
        == "shared_parcel_capacity_partition"
    )


def test_execute_shared_bsm_writes_multiple_footprints_and_one_remainder():
    targets = []
    tasks = []
    candidates = {}
    for index, target_id in enumerate(("shared-project-a", "shared-project-b")):
        target = SiteAreaTarget(
            target_id=target_id,
            site_area_id=target_id,
            name=target_id,
            expected_output_kind="polygon",
            materialization_role="site_footprint",
            classification_decision=ClassificationDecision(
                target_id=target_id,
                code_system="ghytbm",
                candidate_codes=["2124"],
                selected_code="2124",
                decision_mode="rule",
                evidence_refs=[f"claim:{target_id}"],
                status="resolved",
            ),
        )
        candidate_id = f"candidate:{target_id}"
        x0 = index * 0.004
        candidate = CandidateGeometry(
            candidate_id=candidate_id,
            target_id=target_id,
            kind="polygon",
            role="execution_geometry",
            materialization_role="site_footprint",
            wkt=f"POLYGON (({x0} 0, {x0 + 0.003} 0, {x0 + 0.003} 0.01, {x0} 0.01, {x0} 0))",
            spatial_domain_kind="parcel_extent",
            source_bsms=["P-SHARED-EXECUTE"],
            source_area_ha=1.0,
            planning_area_ha=0.2,
            coverage_ratio=0.2,
            availability_status="fully_available",
            eligible_area_ha=1.0,
            evidence_refs=[f"claim:{target_id}"],
            hard_constraint_status="passed",
        )
        candidates[candidate_id] = candidate
        assignment = TargetAssignment(
            target_id=target_id,
            target_type="site_area",
            status="placed",
            selected_bsm="P-SHARED-EXECUTE",
            expected_output_kind="polygon",
            target_binding={**target.model_dump(mode="json"), "candidate_id": candidate_id},
        )
        tasks.append(WorkerTask(
            task_id=f"site_area_footprint:{target_id}",
            worker_type=WorkerType.SITE_AREA_FOOTPRINT,
            target_id=target_id,
            target_type="site_area",
            expected_output_kind="polygon",
            assignment=assignment,
            candidate_id=candidate_id,
            target_binding=dict(assignment.target_binding),
        ))
        targets.append(target)

    state = ExecuteAgentState(
        execution_plan=ExecutionPlan(worker_tasks=tasks),
        candidate_geometry_by_id=candidates,
        parcel_by_bsm={"P-SHARED-EXECUTE": SimpleNamespace(
            bsm="P-SHARED-EXECUTE",
            geometry={
                "type": "Polygon",
                "coordinates": [[[-0.001, -0.001], [0.01, -0.001], [0.01, 0.02], [-0.001, 0.02], [-0.001, -0.001]]],
            },
            area_sqm=10000.0,
            dlbm="0101",
            dlbm_system="gbt21010",
        )},
        land_design_briefs=[],
    )

    result = _project_worker(state)

    assert [change.action for change in result.parcel_changes].count("create") == 2
    assert [change.action for change in result.parcel_changes].count("preserve") == 1
    assert sum(change.new_area_ha for change in result.parcel_changes if change.action == "create") == 0.4
    assert result.parcel_changes[-1].bsm == "shared:P-SHARED-EXECUTE:remainder"
    assert [item.status for item in result.task_results] == ["succeeded", "succeeded"]
    assert len(result.layers[0]["data"]["features"]) == 2


def test_shared_partial_bsm_preserves_eligible_and_excluded_regions_separately():
    parcel = SimpleNamespace(
        bsm="P-PARTIAL-SHARED",
        geometry={
            "type": "Polygon",
            "coordinates": [[[0, 0], [0.01, 0], [0.01, 0.01], [0, 0.01], [0, 0]]],
        },
        dlbm="0101",
        dlbm_system="gbt21010",
    )
    eligible_wkt = "POLYGON ((0 0, 0.007 0, 0.007 0.01, 0 0.01, 0 0))"
    candidates = [
        SimpleNamespace(
            source_area_ha=1.0,
            planning_area_ha=0.2,
            eligible_area_ha=0.7,
            excluded_area_ha=0.3,
            availability_status="partially_available",
            eligible_geometry_wkt=eligible_wkt,
            scenario_id="scenario:partial",
        ),
        SimpleNamespace(
            source_area_ha=1.0,
            planning_area_ha=0.2,
            eligible_area_ha=0.7,
            excluded_area_ha=0.3,
            availability_status="partially_available",
            eligible_geometry_wkt=eligible_wkt,
            scenario_id="scenario:partial",
        ),
    ]
    footprints = [
        ParcelChange(
            bsm="target-a:footprint",
            action="create",
            after_geometry_wkt="POLYGON ((0 0, 0.002 0, 0.002 0.01, 0 0.01, 0 0))",
        ),
        ParcelChange(
            bsm="target-b:footprint",
            action="create",
            after_geometry_wkt="POLYGON ((0.002 0, 0.004 0, 0.004 0.01, 0.002 0.01, 0.002 0))",
        ),
    ]

    changes = _shared_parcel_remainder_changes(
        "P-PARTIAL-SHARED", parcel, candidates, footprints
    )

    assert {change.bsm for change in changes} == {
        "shared:P-PARTIAL-SHARED:remainder",
        "shared:P-PARTIAL-SHARED:excluded",
    }
    assert {change.excluded_area_ha for change in changes} == {0.3}
    assert all(change.availability_status == "partially_available" for change in changes)
