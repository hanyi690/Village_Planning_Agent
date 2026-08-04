"""GROUND review package tests - build_ground_review_package."""

import json

from app.agent.ground.review import build_ground_review_package
from app.modules.schema.contracts.contract_meta import StageIssue
from app.modules.schema.contracts.grounding_contracts import (
    CandidateSite,
    GroundingResult,
    SpatialQueryEvidence,
)
from app.modules.schema.contracts.provenance import Provenance
from app.modules.schema.contracts.spatial_reference_contracts import SpatialReferenceSpec
from app.modules.schema.contracts.workflow_contracts import GateDecision


def _candidate(site_id="site_1_P001", source_parcels=("P001",)):
    return CandidateSite(
        site_id=site_id,
        source_parcels=list(source_parcels),
    )


def _issue(message="unresolved spec"):
    return StageIssue(stage="ground", severity="warning", code="spatial_reference_unresolved", message=message)


def _evidence():
    return SpatialQueryEvidence(
        query_type="resolve_spec:attributive",
        query_params={"type": "attributive"},
        result_count=1,
        result_refs=["P001"],
    )


def _provenance():
    return Provenance(source="ground_aggregate", run_id="run-1", module="ground")


def _spec(spec_type="attributive"):
    return SpatialReferenceSpec(type=spec_type)


def _gate(route="EXPLORE"):
    if route == "PASS":
        return GateDecision(stage="ground", passed=True, feedback_route=None)
    return GateDecision(stage="ground", passed=False, feedback_route=route)


def _result(candidates=(), unresolved=(), evidence=(), provenance=None):
    return GroundingResult(
        candidates=list(candidates),
        unresolved=list(unresolved),
        spatial_query_evidence=list(evidence),
        provenance=provenance or _provenance(),
    )


def test_sections_present():
    result = _result(
        candidates=[_candidate()],
        unresolved=[_issue()],
        evidence=[_evidence()],
    )
    gate = _gate("EXPLORE")
    specs = [_spec("attributive"), _spec("directional")]

    package = build_ground_review_package(result, gate, specs)

    assert set(package.keys()) == {
        "输入规格摘要",
        "已解析候选",
        "未解析原因",
        "空间查询证据",
        "约束覆盖",
        "Gate 决定",
        "来源追溯",
        "规格-候选映射",
    }


def test_input_spec_summary():
    result = _result()
    gate = _gate("PASS")
    specs = [_spec("directional"), _spec("attributive")]

    summary = build_ground_review_package(result, gate, specs)["输入规格摘要"]

    assert summary["total"] == 2
    assert summary["by_type"] == {"directional": 1, "attributive": 1}


def test_resolved_candidates():
    result = _result(candidates=[_candidate(source_parcels=["P001", "P002"])])
    gate = _gate("PASS")

    candidates = build_ground_review_package(result, gate, [])["已解析候选"]

    assert len(candidates) == 1
    assert candidates[0]["site_id"] == "site_1_P001"
    assert candidates[0]["source_parcels_count"] == 2
    assert candidates[0]["source_parcels"] == ["P001", "P002"]


def test_unresolved_reasons():
    result = _result(unresolved=[_issue(message="no candidates for type=composed")])
    gate = _gate("EXPLORE")

    reasons = build_ground_review_package(result, gate, [])["未解析原因"]

    assert len(reasons) == 1
    assert reasons[0]["message"] == "no candidates for type=composed"
    assert reasons[0]["stage"] == "ground"
    assert reasons[0]["severity"] == "warning"
    assert reasons[0]["code"] == "spatial_reference_unresolved"


def test_query_evidence():
    result = _result(evidence=[_evidence()])
    gate = _gate("PASS")

    evidence = build_ground_review_package(result, gate, [])["空间查询证据"]

    assert len(evidence) == 1
    assert evidence[0]["query_type"] == "resolve_spec:attributive"
    assert evidence[0]["result_count"] == 1
    assert evidence[0]["result_refs"] == ["P001"]


def test_gate_decision_section():
    result = _result(candidates=[_candidate()])
    explore_gate = _gate("EXPLORE")

    decision = build_ground_review_package(result, explore_gate, [])["Gate 决定"]

    assert decision["route"] == "EXPLORE"
    assert decision["passed"] is False
    assert decision["rationale"]

    pass_gate = _gate("PASS")
    pass_decision = build_ground_review_package(result, pass_gate, [])["Gate 决定"]

    assert pass_decision["route"] == "PASS"
    assert pass_decision["passed"] is True


def test_spec_candidate_mapping():
    result = _result(
        candidates=[_candidate()],
        unresolved=[_issue()],
    )
    gate = _gate("EXPLORE")
    specs = [_spec("attributive"), _spec("composed")]

    mapping = build_ground_review_package(result, gate, specs)["规格-候选映射"]["mapping"]

    assert len(mapping) == 2
    assert mapping[0]["spec_index"] == 0
    assert mapping[0]["spec_type"] == "attributive"
    assert mapping[0]["status"] == "resolved"
    assert mapping[0]["site_id"] == "site_1_P001"
    assert mapping[1]["spec_index"] == 1
    assert mapping[1]["spec_type"] == "composed"
    assert mapping[1]["status"] == "unresolved"
    assert mapping[1]["site_id"] is None


def test_json_serializable():
    result = _result(
        candidates=[_candidate()],
        unresolved=[_issue()],
        evidence=[_evidence()],
    )
    gate = _gate("EXPLORE")
    specs = [_spec("attributive")]

    package = build_ground_review_package(result, gate, specs)

    json.dumps(package)


def test_constraint_coverage():
    result = _result(candidates=[_candidate()])
    gate = _gate("PASS")

    coverage = build_ground_review_package(result, gate, [])["约束覆盖"]

    assert "no constraint check performed" in coverage.get("note", "")
