"""SELECT gate tests - evaluate_select_gate / select_gate_route."""

from app.agent.select_graph.gate import evaluate_select_gate, select_gate_route
from app.modules.schema.contracts.selection_contracts import (
    EliminatedCandidate,
    RankedCandidate,
    SiteSelectionDecision,
)


def _placed(score=0.9, target_count=1):
    return SiteSelectionDecision(
        selected_combination=["P001"],
        full_ranking=[RankedCandidate(candidate_id="P001", rank=1, score=score)],
        decision_factors={
            "target_count": target_count,
            "placed_count": 1,
            "unplaced_count": 0,
            "best_score_by_target": {"p1": score},
        },
        review_status="auto",
    )


def _partial(target_count=2, score=0.9):
    return SiteSelectionDecision(
        selected_combination=["P001"],
        full_ranking=[RankedCandidate(candidate_id="P001", rank=1, score=score)],
        decision_factors={
            "target_count": target_count,
            "placed_count": 1,
            "unplaced_count": 1,
            "best_score_by_target": {"p1": score},
        },
        review_status="auto",
    )


def _empty():
    return SiteSelectionDecision(
        selected_combination=[],
        full_ranking=[],
        eliminated=[
            EliminatedCandidate(
                candidate_id="P001",
                elimination_reason="hard_filter",
                eliminated_by_constraint="farmland_protection",
            )
        ],
        decision_factors={
            "target_count": 1,
            "placed_count": 0,
            "unplaced_count": 1,
            "best_score_by_target": {},
        },
        review_status="auto",
    )


def test_pass():
    d = evaluate_select_gate(_placed(), target_count=1)

    assert select_gate_route(_placed(), target_count=1) == "PASS"
    assert d.passed is True
    assert d.feedback_route is None
    assert d.stage == "select"


def test_retry_ground_unplaced():
    d = evaluate_select_gate(_empty(), target_count=1)

    assert select_gate_route(_empty(), target_count=1) == "RETRY_GROUND"
    assert d.passed is False
    assert d.feedback_route == "RETRY_GROUND"
    assert d.pending_requests[0].request_type == "selection_no_candidate"
    assert d.pending_requests[0].context["reason"] == "selection_no_candidate"


def test_retry_ground_partial():
    d = evaluate_select_gate(_partial(target_count=2), target_count=2)

    assert select_gate_route(_partial(target_count=2), target_count=2) == "RETRY_GROUND"
    assert d.passed is False
    assert d.feedback_route == "RETRY_GROUND"


def test_human_low_confidence():
    d = evaluate_select_gate(_placed(score=0.2), target_count=1)

    assert select_gate_route(_placed(score=0.2), target_count=1) == "HUMAN"
    assert d.passed is False
    assert d.feedback_route == "HUMAN"
    assert d.pending_requests[0].request_type == "selection_low_confidence"


def test_precedence_retry_over_human():
    d = evaluate_select_gate(_partial(target_count=2, score=0.2), target_count=2)

    assert select_gate_route(_partial(target_count=2, score=0.2), target_count=2) == "RETRY_GROUND"
    assert d.passed is False
    assert d.feedback_route == "RETRY_GROUND"


def test_empty_target_count_pass():
    decision = SiteSelectionDecision(
        selected_combination=[],
        full_ranking=[],
        decision_factors={
            "target_count": 0,
            "placed_count": 0,
            "unplaced_count": 0,
            "best_score_by_target": {},
        },
        review_status="auto",
    )

    d = evaluate_select_gate(decision, target_count=0)

    assert select_gate_route(decision, target_count=0) == "PASS"
    assert d.passed is True
    assert d.feedback_route is None


def test_deterministic():
    d1 = evaluate_select_gate(_placed(score=0.2), target_count=1)
    d2 = evaluate_select_gate(_placed(score=0.2), target_count=1)

    assert d1.model_dump(exclude={"created_at"}) == d2.model_dump(exclude={"created_at"})
