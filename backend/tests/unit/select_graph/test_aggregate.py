"""Unit tests for the SELECT aggregate (select_aggregate)."""

from app.agent.select_graph.aggregate import (
    build_land_design_brief,
    select_aggregate,
)
from app.modules.context.planning_context import PlanningContext
from app.modules.schema.contracts.grounding_contracts import CandidateSite, GroundingResult
from app.modules.schema.contracts.parse_contracts import ProjectTarget, SpatialPlanningIntent
from app.modules.spatial_ops.selection import PlacementDecision, Rejection

from .conftest import make_parcel

_SCORE_KEYS = {"proximity", "construction", "area_fit", "road_access", "service_coverage"}


def _site(source_parcels=("P001",)):
    return CandidateSite(
        site_id=f"site_{len(source_parcels)}",
        source_parcels=list(source_parcels),
    )


def _result(source_parcels=("P001",)):
    return GroundingResult(candidates=[_site(source_parcels)])


def _project(project_id, **kwargs):
    defaults = dict(name=f"proj-{project_id}", scale_text="1.5公顷")
    defaults.update(kwargs)
    return ProjectTarget(project_id=project_id, **defaults)


def _intent(projects):
    return SpatialPlanningIntent(project_targets=list(projects))


def _context(bundle, session_id="s1"):
    return PlanningContext(bundle=bundle, session_id=session_id)


def test_empty_inputs(make_bundle):
    result = GroundingResult()
    intent = SpatialPlanningIntent()
    context = _context(make_bundle([]))

    decision, briefs = select_aggregate(result, intent, context)

    assert decision.selected_combination == []
    assert decision.full_ranking == []
    assert decision.eliminated == []
    assert decision.decision_factors["target_count"] == 0
    assert decision.review_status == "auto"
    assert briefs == []


def test_one_project_one_candidate(make_bundle):
    result = _result(["P001"])
    intent = _intent([_project("p1")])
    context = _context(make_bundle([make_parcel("P001")]))

    decision, briefs = select_aggregate(result, intent, context)

    assert decision.selected_combination == ["P001"]
    assert len(decision.full_ranking) == 1
    assert decision.full_ranking[0].candidate_id == "P001"
    assert decision.full_ranking[0].rank == 1
    assert decision.review_status == "auto"
    assert decision.provenance is not None
    assert decision.provenance.source == "select_aggregate"
    assert len(briefs) == 1
    assert briefs[0].project_ref == "p1"


def test_conflict_two_projects_one_parcel(make_bundle):
    result = _result(["P001"])
    intent = _intent([_project("p1"), _project("p2")])
    context = _context(make_bundle([make_parcel("P001")]))

    decision, briefs = select_aggregate(result, intent, context)

    assert len(decision.selected_combination) == 1
    assert decision.selected_combination[0] == "P001"
    assert decision.decision_factors["placed_count"] == 1
    assert decision.decision_factors["unplaced_count"] == 1
    conflict = [
        e for e in decision.eliminated
        if e.candidate_id == "P001" and "allocated" in e.elimination_reason
    ]
    assert conflict, [e.model_dump() for e in decision.eliminated]
    assert len(briefs) == 1
    assert briefs[0].project_ref == "p1"


def test_score_breakdown_has_five_keys(make_bundle):
    result = _result(["P001", "P002"])
    intent = _intent([_project("p1")])
    context = _context(make_bundle([make_parcel("P001"), make_parcel("P002")]))

    decision, _ = select_aggregate(result, intent, context)

    assert decision.full_ranking
    for ranked in decision.full_ranking:
        assert set(ranked.score_breakdown.keys()) == _SCORE_KEYS


def test_score_breakdown_has_real_values(make_bundle):
    result = _result(["P001"])
    intent = _intent([_project("p1")])
    context = _context(make_bundle([make_parcel("P001")]))

    decision, _ = select_aggregate(result, intent, context)

    assert len(decision.full_ranking) == 1
    ranked = decision.full_ranking[0]
    assert ranked.score > 0
    assert ranked.score_breakdown["proximity"] == 0.0
    assert ranked.score_breakdown["construction"] == 0.3
    assert ranked.score_breakdown["area_fit"] > 0
    assert ranked.score_breakdown["road_access"] == 0.0
    assert ranked.score_breakdown["service_coverage"] == 0.0
    assert decision.decision_factors["best_score_by_target"]["p1"] == ranked.score


def test_land_design_brief_fields(make_bundle):
    result = _result(["P001"])
    project = _project("p1", related_road_targets=["r1"], related_facility_types=["f1"])
    intent = _intent([project])
    context = _context(make_bundle([make_parcel("P001")]))

    _, briefs = select_aggregate(result, intent, context)

    assert len(briefs) == 1
    brief = briefs[0]
    assert any("r1" in r for r in brief.access_requirements)
    assert any("f1" in r for r in brief.adjacency_requirements)
    assert brief.footprint_conditions
    assert brief.area_tolerance_pct == 5.0
    assert brief.preservation_requirements == []


def test_setback_requirements_from_rejections():
    decision = PlacementDecision(
        target_id="p1",
        status="placed",
        rejected=[
            Rejection(
                bsm="P900",
                reason="hard_filter",
                detail=["constraint:farmland_protection,ecological_redline"],
            )
        ],
    )
    project = _project("p1")

    brief = build_land_design_brief(project, decision, None)

    assert set(brief.setback_requirements) == {"farmland_protection", "ecological_redline"}


def test_none_bundle_graceful(make_bundle):
    result = _result(["P001"])
    intent = _intent([_project("p1")])
    context = _context(None)

    decision, briefs = select_aggregate(result, intent, context)

    assert decision.selected_combination == []
    assert decision.full_ranking == []
    assert briefs == []


def test_deterministic(make_bundle):
    result = _result(["P001"])
    intent = _intent([_project("p1"), _project("p2")])
    context = _context(make_bundle([make_parcel("P001")]))

    d1, b1 = select_aggregate(result, intent, context)
    d2, b2 = select_aggregate(result, intent, context)

    assert d1.selected_combination == d2.selected_combination
    assert d1.decision_factors == d2.decision_factors
    assert d1.model_dump(exclude={"created_at": True, "provenance": {"timestamp": True}}) == d2.model_dump(
        exclude={"created_at": True, "provenance": {"timestamp": True}}
    )
    assert [b.model_dump() for b in b1] == [b.model_dump() for b in b2]
