"""GROUND gate tests - evaluate_ground_gate / ground_gate_route."""

from app.agent.ground.gate import evaluate_ground_gate, ground_gate_route
from app.modules.schema.contracts.contract_meta import StageIssue
from app.modules.schema.contracts.grounding_contracts import CandidateSite, GroundingResult


def _candidate(site_id="site_1_P001", source_parcels=("P001",), confidence=0.9):
    return CandidateSite(
        site_id=site_id,
        source_parcels=list(source_parcels),
        metrics={"confidence": confidence},
    )


def _issue(code="spatial_reference_unresolved", message="unresolved spec"):
    return StageIssue(stage="ground", severity="warning", code=code, message=message)


def _result(candidates=(), unresolved=()):
    return GroundingResult(candidates=list(candidates), unresolved=list(unresolved))


def test_pass():
    d = evaluate_ground_gate(_result(candidates=[_candidate()]))

    assert ground_gate_route(_result(candidates=[_candidate()])) == "PASS"
    assert d.passed is True
    assert d.feedback_route is None
    assert d.stage == "ground"


def test_explore():
    result = _result(candidates=[_candidate()], unresolved=[_issue()])

    d = evaluate_ground_gate(result)

    assert ground_gate_route(result) == "EXPLORE"
    assert d.passed is False
    assert d.feedback_route == "EXPLORE"
    assert any(
        r.request_type == "spatial_reference_unresolved"
        and r.context.get("reason") == "spatial_reference_unresolved"
        for r in d.pending_requests
    )


def test_human_ambiguous():
    result = _result(
        candidates=[_candidate(source_parcels=["P001", "P002"], confidence=0.5)]
    )

    d = evaluate_ground_gate(result)

    assert ground_gate_route(result) == "HUMAN"
    assert d.passed is False
    assert d.feedback_route == "HUMAN"


def test_human_not_ambiguous_when_high_confidence():
    result = _result(
        candidates=[_candidate(source_parcels=["P001", "P002"], confidence=0.9)]
    )

    d = evaluate_ground_gate(result)

    assert d.passed is True
    assert d.feedback_route is None


def test_precedence_unresolved_wins():
    result = _result(
        candidates=[_candidate(source_parcels=["P001", "P002"], confidence=0.5)],
        unresolved=[_issue()],
    )

    d = evaluate_ground_gate(result)

    assert d.passed is False
    assert d.feedback_route == "EXPLORE"


def test_empty_result():
    d = evaluate_ground_gate(_result())

    assert ground_gate_route(_result()) == "EXPLORE"
    assert d.passed is False
    assert d.feedback_route == "EXPLORE"


def test_deterministic():
    result = _result(
        candidates=[_candidate(source_parcels=["P001", "P002"], confidence=0.5)]
    )

    d1 = evaluate_ground_gate(result)
    d2 = evaluate_ground_gate(result)

    assert d1.model_dump(exclude={"created_at"}) == d2.model_dump(
        exclude={"created_at"}
    )
