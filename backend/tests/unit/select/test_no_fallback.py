"""Regression: SELECT must NOT fall back to the full candidate pool when a
project has no per-target candidates; it must mark the project unplaced and
route RETRY_GROUND.
"""

from app.agent.select.aggregate import select_aggregate
from app.agent.select.gate import evaluate_select_gate, select_gate_route
from app.modules.context.planning_context import PlanningContext
from app.modules.schema.contracts.grounding_contracts import CandidateSite, GroundingResult
from app.modules.schema.contracts.parse_contracts import ProjectTarget, SpatialPlanningIntent

from .conftest import make_parcel


def _site(site_id, source_parcels, target_ref=None):
    return CandidateSite(
        site_id=site_id,
        source_parcels=list(source_parcels),
        target_ref=target_ref,
    )


def _project(project_id, **kwargs):
    defaults = dict(name=f"proj-{project_id}", scale_text="1.5公顷")
    defaults.update(kwargs)
    return ProjectTarget(project_id=project_id, **defaults)


def _context(bundle, session_id="s1"):
    return PlanningContext(bundle=bundle, session_id=session_id)


def test_no_candidates_not_placed_and_routes_retry_ground(make_bundle):
    result = GroundingResult(
        candidates=[
            _site("s2", ["P002"], target_ref="p2"),
        ]
    )
    intent = SpatialPlanningIntent(project_targets=[_project("p1")])
    context = _context(make_bundle([make_parcel("P002")]))

    decision, briefs = select_aggregate(result, intent, context)

    assert decision.selected_combination == []
    assert decision.decision_factors["target_count"] == 1
    assert decision.decision_factors["placed_count"] == 0
    assert decision.decision_factors["unplaced_count"] == 1
    assert decision.decision_factors["best_score_by_target"]["p1"] == 0.0
    assert "P002" not in decision.selected_combination
    assert "P002" not in [r.candidate_id for r in decision.full_ranking]
    assert "P002" not in [e.candidate_id for e in decision.eliminated]
    assert briefs == []

    gate = evaluate_select_gate(decision, target_count=1)
    assert select_gate_route(decision, target_count=1) == "RETRY_GROUND"
    assert gate.passed is False
    assert gate.feedback_route == "RETRY_GROUND"


def test_mixed_placed_and_no_candidates(make_bundle):
    result = GroundingResult(
        candidates=[
            _site("s1", ["P001"], target_ref="p1"),
            _site("s2", ["P002"], target_ref="p2"),
        ]
    )
    intent = SpatialPlanningIntent(
        project_targets=[_project("p1"), _project("p3")]
    )
    context = _context(
        make_bundle([make_parcel("P001"), make_parcel("P002")])
    )

    decision, briefs = select_aggregate(result, intent, context)

    assert decision.selected_combination == ["P001"]
    assert decision.decision_factors["placed_count"] == 1
    assert decision.decision_factors["unplaced_count"] == 1
    assert "P002" not in decision.selected_combination
    assert len(briefs) == 1

    gate = evaluate_select_gate(decision, target_count=2)
    assert gate.passed is False
    assert gate.feedback_route == "RETRY_GROUND"
