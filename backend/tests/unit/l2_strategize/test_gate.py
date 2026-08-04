"""G2 Strategy Gate tests - evaluate_l2_gate."""
from __future__ import annotations

import pytest
from app.agent.l2_strategize.gate import evaluate_l2_gate
from app.modules.schema.contracts.l2_contracts import (
    L2Strategy,
    StrategyConflict,
    StrategyIssue,
)
from app.modules.schema.contracts.l1_contracts import EvidenceGap
from app.modules.schema.contracts.evidence_contracts import EvidenceSource


def _strategy(**kw) -> L2Strategy:
    defaults = dict(
        development_goals=["目标"],
        spatial_structure="组团状",
        implementation_priorities=["优先"],
        sources=[EvidenceSource(source_type="report", reference="L2:planning_strategies")],
    )
    defaults.update(kw)
    return L2Strategy(**defaults)


def test_pass_when_complete():
    d = evaluate_l2_gate(_strategy())
    assert d.passed is True
    assert d.feedback_route is None


def test_human_when_empty():
    d = evaluate_l2_gate(_strategy(development_goals=[], implementation_priorities=[], spatial_structure=""))
    assert d.passed is False
    assert d.feedback_route == "HUMAN"


def test_l2_when_error_contradiction():
    s = _strategy(
        strategy_issues=[
            StrategyIssue(severity="error", code="strategy_contradiction", message="策略A与策略B矛盾"),
        ]
    )
    d = evaluate_l2_gate(s)
    assert d.passed is False
    assert d.feedback_route == "L2"
    assert any(p.request_type == "strategy_rework" for p in d.pending_requests)


def test_l2_ignores_warning_issues():
    s = _strategy(
        strategy_issues=[StrategyIssue(severity="warning", code="strategy_contradiction", message="轻微")],
        sources=[EvidenceSource(source_type="report", reference="r")],
    )
    d = evaluate_l2_gate(s)
    assert d.passed is True


def test_explore_when_gaps():
    s = _strategy(
        evidence_gaps=[
            EvidenceGap(gap_id="g1", dimension="planning_strategies", description="缺人口数据", severity="warning"),
        ]
    )
    d = evaluate_l2_gate(s)
    assert d.passed is False
    assert d.feedback_route == "EXPLORE"
    assert any(p.request_type == "evidence_gap" for p in d.pending_requests)


def test_explore_when_no_sources():
    s = _strategy(sources=[])
    d = evaluate_l2_gate(s)
    assert d.passed is False
    assert d.feedback_route == "EXPLORE"


def test_pass_with_sources_and_warning_gaps_resolved():
    s = _strategy(
        sources=[EvidenceSource(source_type="report", reference="L2:planning_strategies")],
        strategy_conflicts=[StrategyConflict(description="轻微冲突", severity="warning")],
    )
    d = evaluate_l2_gate(s)
    assert d.passed is True
