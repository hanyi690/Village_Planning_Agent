from app.contracts.spatial.candidate_geometry import CandidateGeometry
from app.contracts.spatial.grounded_problem import (
    GroundedCandidateDomain,
    GroundedPlanningProblem,
    GroundedTargetDomain,
)
from app.contracts.spatial.grounding_contracts import CandidateSite, GroundingResult
from app.domain.ground.gate import evaluate_ground_gate, ground_gate_route


def _geometry() -> CandidateGeometry:
    return CandidateGeometry(
        candidate_id="candidate:site-1",
        target_id="target:site-1",
        kind="polygon",
        role="execution_geometry",
        materialization_role="site_footprint",
        wkt="POLYGON ((0 0, 1 0, 1 1, 0 0))",
        granularity="parcel_extent",
        spatial_domain_kind="parcel_extent",
        source_ref="source:parcel-1",
        evidence_refs=["evidence:parcel-1"],
        identity_confidence=0.95,
        geometry_confidence=0.95,
        hard_constraint_status="passed",
        availability_status="fully_available",
        source_bsms=["bsm:parcel-1"],
        source_area_ha=2,
        eligible_area_ha=2,
        planning_area_ha=1,
    )


def _problem(*, domain_status: str) -> GroundedPlanningProblem:
    geometry = _geometry()
    return GroundedPlanningProblem(
        target_domains=[GroundedTargetDomain(
            target_id="target:site-1",
            target_kind="site_area",
            expected_output_kind="polygon",
            candidate_site_refs=[geometry.candidate_id],
            evidence_refs=["evidence:target-1"],
            status=domain_status,
        )],
        candidate_domains=[GroundedCandidateDomain(
            target_id="target:site-1",
            candidate_ids=[geometry.candidate_id],
            candidate_geometry_refs=[geometry.candidate_id],
            status=domain_status,
        )],
        candidate_geometries=[geometry],
    )


def test_ground_gate_does_not_pass_candidate_only_problem_after_human_deferral():
    geometry = _geometry()
    result = GroundingResult(
        candidates=[CandidateSite(
            site_id=geometry.candidate_id,
            target_ref="target:site-1",
            geometry=geometry,
        )],
        problem=_problem(domain_status="candidate_only"),
    )

    assert ground_gate_route(result) == "HUMAN"
    gate = evaluate_ground_gate(result)
    assert gate.feedback_route == "HUMAN"
    assert any(
        request.request_type == "ground_problem_readiness"
        and request.context["reason"].startswith("candidate_")
        for request in gate.pending_requests
    )


def test_ground_gate_keeps_closed_problem_passable():
    geometry = _geometry()
    result = GroundingResult(
        candidates=[CandidateSite(
            site_id=geometry.candidate_id,
            target_ref="target:site-1",
            geometry=geometry,
        )],
        problem=_problem(domain_status="resolved"),
    )

    assert ground_gate_route(result) == "PASS"
    assert evaluate_ground_gate(result).passed is True
