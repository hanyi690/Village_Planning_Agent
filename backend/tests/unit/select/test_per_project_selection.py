"""Per-project candidate pools, extended scoring, and facility MCLP placement."""

import pytest

from app.agent.select.adapter import (
    filter_parcels_for_target,
    grounding_to_candidate_parcels,
)
from app.agent.select.aggregate import select_aggregate
from app.modules.context.planning_context import PlanningContext
from app.modules.schema.contracts.grounding_contracts import CandidateSite, GroundingResult
from app.modules.schema.contracts.parse_contracts import FacilityTarget, ProjectTarget, SpatialPlanningIntent
from app.modules.spatial_ops.selection import CandidateParcel, score_candidates

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


def _context(bundle, session_id="s1", village_anchors=None):
    return PlanningContext(
        bundle=bundle,
        session_id=session_id,
        village_anchors=village_anchors or [],
    )


def _p(bsm, dlmc, area_ha, distance_m):
    return CandidateParcel(
        bsm=bsm, geometry={}, dlmc=dlmc, area_ha=area_ha, distance_m=distance_m
    )


def test_pool_filtered_per_project(make_bundle):
    s1 = _site("s1", ["P001"], target_ref="p1")
    s2 = _site("s2", ["P002"], target_ref="p2")
    s3 = _site("s3", ["P003"])
    result = GroundingResult(candidates=[s1, s2, s3])
    bundle = make_bundle(
        [make_parcel("P001"), make_parcel("P002"), make_parcel("P003")]
    )
    pool = grounding_to_candidate_parcels(result, bundle)

    filtered = filter_parcels_for_target(pool, "p1")
    bsms = {p.bsm for p in filtered}

    assert "P001" in bsms
    assert "P003" in bsms
    assert "P002" not in bsms


def test_score_extended_backward_compat():
    scored = score_candidates(
        [_p("far", "空闲宅基地", 0.1, 2000), _p("near", "空闲宅基地", 0.1, 100)],
        cluster_centroid=(0.0, 0.0),
    )
    assert scored[0].bsm == "near"


def test_score_extended_uses_new_criteria():
    scored = score_candidates(
        [_p("a", "空闲宅基地", 0.15, 100), _p("b", "空闲宅基地", 0.15, 100)],
        cluster_centroid=(0.0, 0.0),
        road_distance_m={"a": 50.0, "b": 900.0},
        project_type="industrial",
    )
    assert scored[0].bsm == "a"


def test_select_uses_per_project_pool(make_bundle):
    result = GroundingResult(
        candidates=[
            _site("s1", ["P001"], target_ref="p1"),
            _site("s2", ["P002"], target_ref="p2"),
        ]
    )
    intent = SpatialPlanningIntent(
        project_targets=[_project("p1"), _project("p2")]
    )
    context = _context(
        make_bundle(
            [make_parcel("P001", dlbm="0101"), make_parcel("P002", dlbm="0702")]
        )
    )

    decision, _ = select_aggregate(result, intent, context)

    p1_ranked = [r for r in decision.full_ranking if r.project_ref == "p1"]
    assert p1_ranked
    assert p1_ranked[0].candidate_id == "P001"
    assert all(r.candidate_id != "P002" for r in p1_ranked)
    assert decision.full_ranking[0].project_ref == "p1"


def test_facility_mclp_sets_anchor(make_bundle):
    result = GroundingResult(
        candidates=[
            _site("s1", ["P001"], target_ref="p1"),
            _site("s2", ["P003"]),
        ]
    )
    facility = FacilityTarget(
        type="文化活动室",
        status="planned_new",
        service_radius=20000,
        candidate_bsms=["P003"],
    )
    intent = SpatialPlanningIntent(
        project_targets=[_project("p1")],
        facilities=[facility],
    )
    context = _context(
        make_bundle([make_parcel("P001"), make_parcel("P003")]),
        village_anchors=[{"lon": 0.5, "lat": 0.5}],
    )

    decision, _ = select_aggregate(result, intent, context)

    assert facility.anchor_point is not None
    assert facility.anchor_point[0] == pytest.approx(0.5, abs=1e-6)
    assert facility.anchor_point[1] == pytest.approx(0.5, abs=1e-6)
    assert decision.decision_factors["facility_count"] == 1
    placed = decision.decision_factors["facility_placements"]["facility_0"]
    assert placed["status"] == "placed"
    assert placed["facility_type"] == "文化活动室"
    assert placed["bsm"] == "P003"
