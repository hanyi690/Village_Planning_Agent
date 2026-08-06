"""Tests for G1 Evidence Gate evaluator."""
from __future__ import annotations

from app.agent.l1_observe.gate import evaluate_l1_gate
from app.modules.schema.contracts.contract_meta import StageIssue
from app.modules.schema.contracts.evidence_contracts import EvidenceSource
from app.modules.schema.contracts.l1_contracts import EvidenceGap, L1Snapshot
from app.modules.schema.contracts.workflow_contracts import GateDecision


def _base_snapshot(**overrides) -> L1Snapshot:
    defaults = dict(
        context_version="v1",
        artifact_id="l1-1",
        facts=["村域人口 3200 人"],
        constraints=["基本农田保护红线"],
        issues=[],
        opportunities=[],
        evidence_gaps=[],
        sources=[EvidenceSource(source_type="report", reference="ref-l1-1")],
    )
    defaults.update(overrides)
    return L1Snapshot(**defaults)


def test_gate_passes_when_facts_sources_complete_no_gaps():
    decision = evaluate_l1_gate(_base_snapshot(), run_id="r1", context_version="v1")
    assert isinstance(decision, GateDecision)
    assert decision.passed is True
    assert decision.feedback_route is None
    assert decision.stage == "l1"


def test_gate_routes_to_explore_when_evidence_gaps_exist():
    decision = evaluate_l1_gate(
        _base_snapshot(
            evidence_gaps=[
                EvidenceGap(gap_id="g1", dimension="infrastructure", description="缺少供水管网", severity="warning"),
            ]
        ),
        run_id="r1", context_version="v1",
    )
    assert decision.passed is False
    assert decision.feedback_route == "EXPLORE"
    assert "缺少供水管网" in decision.evidence_requests
    assert any(p.stage == "explore" for p in decision.pending_requests)


def test_gate_routes_to_l1_on_fact_contradiction():
    decision = evaluate_l1_gate(
        _base_snapshot(
            issues=[
                StageIssue(stage="l1", severity="error", code="fact_contradiction", message="人口与用地矛盾"),
            ]
        ),
        run_id="r1", context_version="v1",
    )
    assert decision.passed is False
    assert decision.feedback_route == "L1"


def test_gate_routes_to_human_when_snapshot_empty():
    snap = L1Snapshot(context_version="v1", artifact_id="l1-empty")
    decision = evaluate_l1_gate(snap, run_id="r1", context_version="v1")
    assert decision.passed is False
    assert decision.feedback_route == "HUMAN"


def test_gate_passes_when_no_sources_but_facts_present():
    decision = evaluate_l1_gate(_base_snapshot(sources=[]), run_id="r1", context_version="v1")
    assert decision.passed is True
    assert decision.feedback_route is None


def test_gate_routes_to_explore_when_no_facts_and_no_sources():
    snap = _base_snapshot(sources=[], facts=[])
    decision = evaluate_l1_gate(snap, run_id="r1", context_version="v1")
    assert decision.passed is False
    assert decision.feedback_route == "EXPLORE"


def test_gate_pending_requests_carry_gap_ids():
    decision = evaluate_l1_gate(
        _base_snapshot(
            evidence_gaps=[
                EvidenceGap(gap_id="g-infra-0", dimension="infrastructure", description="缺水网"),
            ]
        ),
        run_id="r1", context_version="v1",
    )
    flat = str(decision.pending_requests[0].context)
    assert "g-infra-0" in flat
