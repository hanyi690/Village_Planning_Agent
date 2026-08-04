"""L3 review package builder tests."""
from __future__ import annotations

from app.agent.l3_plan.review import build_l3_review_package, build_summary_md
from app.modules.ports.artifact_store import ArtifactRef
from app.modules.schema.contracts.evidence_contracts import EvidenceSource
from app.modules.schema.contracts.l1_contracts import EvidenceGap
from app.modules.schema.contracts.l3_contracts import (
    InterventionDependency,
    PlanningIntervention,
    PlanningProgram,
    ProgramIssue,
)
from app.modules.schema.contracts.review_contracts import ReviewPackage, ReviewStatus
from app.modules.schema.contracts.workflow_contracts import GateDecision


def _program() -> PlanningProgram:
    return PlanningProgram(
        interventions=[
            PlanningIntervention(intervention_id="i1", name="休闲农业园", category="project", scale="30公顷"),
            PlanningIntervention(intervention_id="i2", name="游客服务中心", category="facility", scale="2000平米"),
        ],
        dependencies=[InterventionDependency(from_intervention_id="i1", to_intervention_id="i2")],
        omissions=["消防通道"],
        program_issues=[ProgramIssue(severity="warning", code="note", message="需关注")],
        evidence_gaps=[
            EvidenceGap(
                gap_id="g1", dimension="project_bank",
                description="缺项目时序", severity="warning",
            )
        ],
        sources=[EvidenceSource(source_type="report", reference="L3:project_bank")],
    )


def _artifact_ref() -> ArtifactRef:
    return ArtifactRef(
        context_version="v1", artifact_id="l3-1", module="l3_plan",
        run_id="r1", artifact_type="PlanningProgram", revision="v1",
    )


def _gate(passed: bool = True) -> GateDecision:
    return GateDecision(
        stage="l3", passed=passed,
        feedback_route=None if passed else "EXPLORE",
        context_version="v1", artifact_id="gate-l3-1",
    )


def test_build_summary_md_contains_sections():
    p = _program()
    d = _gate()
    md = build_summary_md(p, d)
    assert "L3 PLAN" in md
    assert "休闲农业园" in md
    assert "游客服务中心" in md
    assert "i1 -> i2" in md
    assert "消防通道" in md
    assert "note" in md
    assert "缺项目时序" in md


def test_build_summary_md_contains_gate_outcome():
    md = build_summary_md(_program(), _gate(passed=False))
    assert "EXPLORE" in md


def test_build_review_package_returns_review_package():
    p = _program()
    ref = _artifact_ref()
    d = _gate()
    pkg = build_l3_review_package(program=p, artifact_ref=ref, gate_decision=d, run_id="r1")
    assert isinstance(pkg, ReviewPackage)
    assert "L3 PLAN" in pkg.summary_md
    assert pkg.module == "l3_plan"
    assert pkg.run_id == "r1"
    assert pkg.status == ReviewStatus.AWAITING_REVIEW
    assert pkg.artifact_ref is not None
    assert pkg.artifact_ref.artifact_id == "l3-1"
    assert pkg.artifact_ref.module == "l3_plan"
    assert pkg.artifact_ref.run_id == "r1"
    assert pkg.artifact_ref.artifact_type == "PlanningProgram"
    assert pkg.artifact_ref.revision == "v1"
    assert pkg.summary_md
