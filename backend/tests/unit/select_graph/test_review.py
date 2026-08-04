"""SELECT review package tests - build_select_review_package + build_preview_geojson."""

import json

from app.agent.select_graph.gate import evaluate_select_gate
from app.agent.select_graph.review import (
    build_preview_geojson,
    build_select_review_package,
)
from app.modules.schema.contracts.grounding_contracts import CandidateSite, GroundingResult
from app.modules.schema.contracts.provenance import Provenance
from app.modules.schema.contracts.selection_contracts import (
    EliminatedCandidate,
    LandDesignBrief,
    RankedCandidate,
    SiteSelectionDecision,
)
from app.modules.schema.contracts.workflow_contracts import GateDecision

_SECTION_KEYS = {
    "输入候选摘要",
    "完整排名",
    "淘汰理由",
    "最终组合",
    "决策因子",
    "Gate 决定",
    "来源追溯",
    "地图预览",
}


def _decision(eliminated=()):
    return SiteSelectionDecision(
        selected_combination=["P001"],
        full_ranking=[
            RankedCandidate(
                candidate_id="P001",
                rank=1,
                score=0.9,
                score_breakdown={
                    "proximity": 0.5,
                    "construction": 0.3,
                    "area_fit": 0.2,
                    "road_access": 0.0,
                    "service_coverage": 0.0,
                },
            )
        ],
        eliminated=list(eliminated),
        decision_factors={
            "target_count": 1,
            "placed_count": 1,
            "unplaced_count": 0,
            "best_score_by_target": {"p1": 0.9},
        },
        review_status="auto",
        provenance=Provenance(source="select_aggregate", run_id="r1", module="x"),
    )


def _result():
    return GroundingResult(
        candidates=[CandidateSite(site_id="s1", source_parcels=["P001"])]
    )


def _brief():
    return LandDesignBrief(project_ref="p1")


def _gate(decision, route="PASS"):
    if route == "PASS":
        return evaluate_select_gate(decision, target_count=1)
    return GateDecision(stage="select", passed=False, feedback_route=route)


def _parcel_by_bsm():
    return {
        "P001": {
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[0, 0], [0, 1], [1, 1], [1, 0], [0, 0]]],
            }
        }
    }


def _package(decision=None, briefs=None, gate=None, result=None, parcel_by_bsm=None):
    decision = decision or _decision()
    briefs = briefs if briefs is not None else [_brief()]
    gate = gate or _gate(decision)
    result = result or _result()
    return build_select_review_package(
        decision, briefs, gate, result, parcel_by_bsm=parcel_by_bsm
    )


def test_sections_present():
    assert set(_package().keys()) == _SECTION_KEYS


def test_input_candidate_summary():
    summary = _package()["输入候选摘要"]

    assert summary["candidate_site_count"] == 1
    assert summary["source_parcels_total"] == 1
    assert summary["sites"] == [{"site_id": "s1", "source_parcels_count": 1}]


def test_full_ranking():
    ranking = _package()["完整排名"]

    assert len(ranking) == 1
    entry = ranking[0]
    assert entry["candidate_id"] == "P001"
    assert entry["rank"] == 1
    assert entry["score"] == 0.9
    assert entry["score_breakdown"]["proximity"] == 0.5


def test_eliminated():
    decision = _decision(
        eliminated=[
            EliminatedCandidate(
                candidate_id="P002",
                elimination_reason="hard_filter",
                eliminated_by_constraint="farmland_protection",
            )
        ]
    )

    eliminated = _package(decision=decision)["淘汰理由"]

    assert len(eliminated) == 1
    assert eliminated[0]["candidate_id"] == "P002"
    assert eliminated[0]["elimination_reason"] == "hard_filter"
    assert eliminated[0]["eliminated_by_constraint"] == "farmland_protection"


def test_final_combination():
    final = _package()["最终组合"]

    assert final["selected_combination"] == ["P001"]
    assert final["briefs"][0]["project_ref"] == "p1"
    assert final["briefs"][0]["area_tolerance_pct"] == 5.0


def test_gate_decision_section():
    decision = _decision()

    pass_decision = _package(gate=_gate(decision, "PASS"))["Gate 决定"]

    assert pass_decision["route"] == "PASS"
    assert pass_decision["passed"] is True
    assert pass_decision["feedback_route"] is None
    assert pass_decision["rationale"]

    retry_gate = _package(gate=_gate(decision, "RETRY_GROUND"))["Gate 决定"]

    assert retry_gate["route"] == "RETRY_GROUND"
    assert retry_gate["passed"] is False
    assert retry_gate["feedback_route"] == "RETRY_GROUND"
    assert retry_gate["rationale"]


def test_provenance():
    provenance = _package()["来源追溯"]

    assert provenance["source"] == "select_aggregate"
    assert provenance["run_id"] == "r1"


def test_provenance_empty():
    decision = _decision()
    decision.provenance = None

    assert _package(decision=decision)["来源追溯"] == {}


def test_json_serializable():
    json.dumps(_package())


def test_preview_geojson():
    decision = _decision()
    preview = build_preview_geojson(decision, _parcel_by_bsm())

    assert preview["type"] == "FeatureCollection"
    assert preview["properties"]["note"] == "SELECT map preview: selected parcels"
    assert len(preview["features"]) == 1
    feature = preview["features"][0]
    assert feature["type"] == "Feature"
    assert feature["properties"]["source_bsm"] == "P001"
    assert feature["properties"]["rank"] == 1
    assert feature["properties"]["score"] == 0.9
    assert feature["geometry"]["type"] == "Polygon"


def test_preview_skips_unknown_bsm():
    decision = SiteSelectionDecision(
        selected_combination=["P001", "P002"],
        full_ranking=[
            RankedCandidate(candidate_id="P001", rank=1, score=0.9),
            RankedCandidate(candidate_id="P002", rank=2, score=0.8),
        ],
        decision_factors={
            "target_count": 2,
            "placed_count": 2,
            "unplaced_count": 0,
            "best_score_by_target": {"p1": 0.9, "p2": 0.8},
        },
        review_status="auto",
    )

    preview = build_preview_geojson(decision, _parcel_by_bsm())

    assert len(preview["features"]) == 1
    assert preview["features"][0]["properties"]["source_bsm"] == "P001"


def test_preview_empty_parcels():
    preview = build_preview_geojson(_decision(), {})

    assert preview["type"] == "FeatureCollection"
    assert preview["features"] == []


def test_preview_none_parcels():
    preview = build_preview_geojson(_decision(), None)

    assert preview["features"] == []
