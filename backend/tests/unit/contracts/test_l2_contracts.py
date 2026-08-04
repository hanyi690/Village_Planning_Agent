"""L2 STRATEGIZE contract tests - Wave D enrichment."""

from __future__ import annotations

from app.modules.schema.contracts.evidence_contracts import EvidenceSource
from app.modules.schema.contracts.l1_contracts import EvidenceGap
from app.modules.schema.contracts.l2_contracts import (
    L2Strategy,
    L2StrategyFragment,
    StrategyConflict,
    StrategyIssue,
)
from app.modules.schema.contracts.provenance import Provenance


def test_l2_strategy_enriched_fields():
    s = L2Strategy(
        development_goals=["目标1"],
        spatial_structure="组团状",
        implementation_priorities=["优先发展农业"],
        strategy_conflicts=[StrategyConflict(description="冲突", severity="warning")],
        evidence_refs=["r1"],
        evidence_gaps=[EvidenceGap(gap_id="g1", dimension="planning_strategies", description="缺人口数据")],
        sources=[EvidenceSource(source_type="report", reference="L2:planning_strategies")],
        strategy_issues=[StrategyIssue(severity="error", code="strategy_contradiction", message="策略矛盾")],
        dimension_provenance=[Provenance(source="l2_observe", run_id="r1", module="l2_observe")],
    )
    assert s.evidence_gaps[0].gap_id == "g1"
    assert s.sources[0].source_type == "report"
    assert s.strategy_issues[0].code == "strategy_contradiction"
    assert s.dimension_provenance[0].run_id == "r1"
    assert s.development_goals == ["目标1"]
    assert s.strategy_conflicts[0].description == "冲突"


def test_l2_strategy_fragment_fields():
    f = L2StrategyFragment(
        dimension_key="planning_strategies",
        goals=["人口规模 2000"],
        strategies=["发展休闲农业"],
        priorities=["优先发展"],
        conflicts=[StrategyConflict(description="c")],
        evidence_gaps=[EvidenceGap(gap_id="g", dimension="d", description="x")],
        strategy_issues=[StrategyIssue(code="c", message="m")],
        spatial_structure="组团状",
    )
    assert f.dimension_key == "planning_strategies"
    assert f.goals == ["人口规模 2000"]
    assert f.strategies == ["发展休闲农业"]
    assert f.priorities == ["优先发展"]
    assert f.conflicts[0].description == "c"
    assert f.evidence_gaps[0].gap_id == "g"
    assert f.strategy_issues[0].code == "c"
    assert f.spatial_structure == "组团状"
    assert f.provenance is None
    assert f.trace is None


def test_strategy_issue_mirrors_stage_issue():
    i = StrategyIssue(severity="error", code="strategy_contradiction", message="x", detail="detail")
    assert i.stage == "l2"
    assert i.severity == "error"
    assert i.code == "strategy_contradiction"
    assert i.detail == "detail"


def test_l2_strategy_legacy_construction():
    s = L2Strategy(
        development_goals=["A"],
        spatial_structure="x",
        implementation_priorities=["p"],
        strategy_conflicts=[StrategyConflict(description="d")],
        evidence_refs=["r"],
    )
    assert s.development_goals == ["A"]
    assert s.spatial_structure == "x"
    assert s.evidence_refs == ["r"]
