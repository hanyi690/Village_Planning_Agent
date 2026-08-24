from app.contracts.spatial.grounded_problem import (
    GroundedCandidateDomain,
    GroundedPlanningProblem,
    GroundedTargetDomain,
)
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
                candidate_geometry_refs=["geometry-1"],
                selection_mode="choose_one",
                status="resolved",
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
                candidate_geometry_refs=["geometry-1"],
                geometry_uncertainty_radius_m=250,
                geometry_uncertainty_reasons=["grounded_anchor"],
                status="resolved",
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
    )

    assert problem.candidate_completeness.status == expected
    assert problem.can_solve is False
