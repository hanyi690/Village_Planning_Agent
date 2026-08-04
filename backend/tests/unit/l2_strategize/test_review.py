"""L2 review package builder tests."""
from __future__ import annotations

from app.agent.l2_strategize.review import build_l2_review_package, build_summary_md
from app.modules.ports.artifact_store import ArtifactRef
from app.modules.schema.contracts.evidence_contracts import EvidenceSource
from app.modules.schema.contracts.l1_contracts import EvidenceGap
from app.modules.schema.contracts.l2_contracts import L2Strategy, StrategyConflict, StrategyIssue
from app.modules.schema.contracts.review_contracts import ReviewPackage, ReviewStatus
from app.modules.schema.contracts.workflow_contracts import GateDecision


def _strategy() -> L2Strategy:
    return L2Strategy(
        context_version="v1",
        artifact_id="l2-001",
        development_goals=["建成休闲农业示范村"],
        spatial_structure="组团状",
        implementation_priorities=["优先发展生态农业"],
        strategy_conflicts=[StrategyConflict(description="生态与开发矛盾", severity="warning")],
        strategy_issues=[StrategyIssue(severity="warning", code="note", message="需关注")],
        evidence_gaps=[
            EvidenceGap(
                gap_id="g1", dimension="planning_strategies",
                description="缺人口数据", severity="warning",
            )
        ],
        sources=[EvidenceSource(source_type="report", reference="L2:planning_strategies")],
    )


def _artifact_ref() -> ArtifactRef:
    return ArtifactRef(
        context_version="v1", artifact_id="l2-001", module="l2_strategize",
        run_id="r1", artifact_type="L2Strategy", revision="v1",
    )


def _gate(passed: bool = True) -> GateDecision:
    return GateDecision(
        stage="l2", passed=passed,
        feedback_route=None if passed else "EXPLORE",
        context_version="v1", artifact_id="gate-l2-001",
    )


def test_build_summary_md_contains_sections():
    s = _strategy()
    d = _gate()
    md = build_summary_md(s, d)
    assert "L2 STRATEGIZE" in md
    assert "休闲农业示范村" in md
    assert "生态与开发矛盾" in md
    assert "缺人口数据" in md


def test_build_summary_md_contains_gate_outcome():
    md = build_summary_md(_strategy(), _gate(passed=False))
    assert "EXPLORE" in md


def test_build_review_package_returns_review_package():
    pkg = build_l2_review_package(
        strategy=_strategy(),
        artifact_ref=_artifact_ref(),
        gate_decision=_gate(),
        run_id="r1",
    )
    assert isinstance(pkg, ReviewPackage)
    assert pkg.module == "l2_strategize"
    assert pkg.run_id == "r1"
    assert pkg.status == ReviewStatus.AWAITING_REVIEW
    assert pkg.artifact_ref is not None
    assert pkg.artifact_ref.artifact_id == "l2-001"
    assert "L2 STRATEGIZE" in pkg.summary_md
    assert pkg.summary_md
