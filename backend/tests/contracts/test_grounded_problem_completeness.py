from app.contracts.spatial.grounded_problem import (
    GroundedCandidateDomain,
    GroundedPlanningProblem,
    GroundedTargetDomain,
)
from app.contracts.spatial.candidate_geometry import CandidateGeometry
import pytest


def test_grounded_problem_reports_candidate_complete_only_with_geometry() -> None:
    problem = GroundedPlanningProblem(
        target_domains=[
            GroundedTargetDomain(
                target_id="facility-1",
                target_kind="facility",
                candidate_site_refs=["candidate-1"],
                evidence_refs=["claim-1"],
                status="resolved",
            )
        ],
        candidate_domains=[
            GroundedCandidateDomain(
                target_id="facility-1",
                candidate_ids=["candidate-1"],
                candidate_geometry_refs=["candidate-1"],
                selection_mode="choose_one",
                status="resolved",
            )
        ],
        candidate_geometries=[
            CandidateGeometry(
                candidate_id="candidate-1",
                target_id="facility-1",
                kind="point",
                role="execution_geometry",
                wkt="POINT (0 0)",
                materialization_role="site_footprint",
                source_ref="ground:candidate-1",
                evidence_refs=["ground:candidate-1"],
                identity_confidence=0.9,
                geometry_confidence=0.9,
                hard_constraint_status="passed",
            )
        ],
    )

    assert problem.candidate_completeness.status == "candidate_complete"
    assert problem.candidate_completeness.ready is True
    assert problem.can_solve is True


def test_grounded_problem_stays_incomplete_when_geometry_is_missing() -> None:
    problem = GroundedPlanningProblem(
        target_domains=[
            GroundedTargetDomain(
                target_id="facility-1",
                candidate_site_refs=["candidate-1"],
                status="resolved",
            )
        ],
        candidate_domains=[
            GroundedCandidateDomain(
                target_id="facility-1",
                candidate_ids=["candidate-1"],
                status="candidate_only",
            )
        ],
    )

    assert problem.candidate_completeness.status == "incomplete"
    assert problem.candidate_completeness.ready is False
    assert problem.can_solve is False


def test_grounded_problem_is_not_groundable_when_unresolved_exists() -> None:
    problem = GroundedPlanningProblem(
        unresolved=[
            {
                "code": "missing_geometry",
                "severity": "error",
                "message": "candidate geometry is unavailable",
                "target_id": "facility-1",
            }
        ]
    )

    assert problem.candidate_completeness.status == "not_groundable"
    assert problem.can_solve is False


def test_grounded_problem_requires_review_for_degraded_geometry() -> None:
    problem = GroundedPlanningProblem(
        target_domains=[
            GroundedTargetDomain(
                target_id="facility-1",
                candidate_site_refs=["candidate-1"],
                geometry_roles=["execution_geometry"],
                status="resolved",
            )
        ],
        candidate_domains=[
            GroundedCandidateDomain(
                target_id="facility-1",
                candidate_ids=["candidate-1"],
                candidate_geometry_refs=["candidate-1"],
                geometry_uncertainty_radius_m=250,
                geometry_uncertainty_reasons=["grounded_anchor"],
                status="resolved",
            )
        ],
        candidate_geometries=[
            CandidateGeometry(
                candidate_id="candidate-1",
                target_id="facility-1",
                kind="point",
                role="execution_geometry",
                wkt="POINT (0 0)",
                materialization_role="site_footprint",
                source_ref="ground:candidate-1",
                evidence_refs=["ground:candidate-1"],
                identity_confidence=0.9,
                geometry_confidence=0.9,
                hard_constraint_status="passed",
            )
        ],
    )

    assert problem.candidate_completeness.status == "human_required"
    assert problem.candidate_completeness.degraded_geometry_target_ids == ("facility-1",)
    assert problem.can_solve is False


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("candidate_only", "human_required"),
        ("ambiguous", "human_required"),
        ("unresolved", "not_groundable"),
    ],
)
def test_candidate_domain_status_is_part_of_grounding_completeness(
    status: str,
    expected: str,
) -> None:
    problem = GroundedPlanningProblem(
        target_domains=[
            GroundedTargetDomain(
                target_id="facility-1",
                candidate_site_refs=["candidate-1"],
                status="resolved",
            )
        ],
        candidate_domains=[
            GroundedCandidateDomain(
                target_id="facility-1",
                candidate_ids=["candidate-1"],
                candidate_geometry_refs=["candidate-1"],
                status=status,
            )
        ],
        candidate_geometries=[
            CandidateGeometry(
                candidate_id="candidate-1",
                target_id="facility-1",
                kind="point",
                role="execution_geometry",
                wkt="POINT (0 0)",
                materialization_role="site_footprint",
                source_ref="ground:candidate-1",
                evidence_refs=["ground:candidate-1"],
                identity_confidence=0.9,
                geometry_confidence=0.9,
                hard_constraint_status="passed",
            )
        ],
    )

    assert problem.candidate_completeness.status == expected
    assert problem.can_solve is False


def test_resolved_domains_are_downgraded_when_replayed_geometry_has_only_legacy_confidence() -> None:
    problem = GroundedPlanningProblem(
        target_domains=[
            GroundedTargetDomain(
                target_id="legacy-facility",
                candidate_site_refs=["legacy-candidate"],
                geometry_roles=["execution_geometry"],
                status="resolved",
            )
        ],
        candidate_domains=[
            GroundedCandidateDomain(
                target_id="legacy-facility",
                candidate_ids=["legacy-candidate"],
                candidate_geometry_refs=["legacy-candidate"],
                selection_mode="choose_one",
                status="resolved",
            )
        ],
        candidate_geometries=[
            CandidateGeometry(
                candidate_id="legacy-candidate",
                target_id="legacy-facility",
                kind="polygon",
                role="execution_geometry",
                materialization_role="site_footprint",
                wkt="POLYGON ((0 0, 1 0, 1 1, 0 1, 0 0))",
                source_ref="legacy:facility",
                evidence_refs=["legacy:facility"],
                confidence=0.9,
                hard_constraint_status="passed",
                availability_status="fully_available",
            )
        ],
    )

    assert problem.candidate_domains[0].status == "resolved"
    assert problem.target_domains[0].status == "resolved"
    assert problem.candidate_geometries[0].grounding_ready is False
    assert problem.candidate_completeness.status == "human_required"
    assert problem.can_solve is False
