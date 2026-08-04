"""G3 Program Gate tests - evaluate_l3_gate."""
from __future__ import annotations

import pytest
from app.agent.l3_plan.gate import evaluate_l3_gate
from app.modules.schema.contracts.l3_contracts import (
    PlanningProgram,
    PlanningIntervention,
    InterventionDependency,
    ProgramIssue,
)
from app.modules.schema.contracts.l1_contracts import EvidenceGap
from app.modules.schema.contracts.evidence_contracts import EvidenceSource


def _program(**kw) -> PlanningProgram:
    defaults = dict(
        interventions=[PlanningIntervention(intervention_id="i1", name="项目A")],
        sources=[EvidenceSource(source_type="report", reference="L3:project_bank")],
    )
    defaults.update(kw)
    return PlanningProgram(**defaults)


def test_pass_when_complete():
    d = evaluate_l3_gate(_program())
    assert d.passed is True
    assert d.feedback_route is None


def test_human_when_empty():
    d = evaluate_l3_gate(_program(interventions=[], dependencies=[], sources=[]))
    assert d.passed is False
    assert d.feedback_route == "HUMAN"


def test_l3_when_error_contradiction():
    p = _program(
        program_issues=[ProgramIssue(severity="error", code="program_contradiction", message="项目A与项目B重叠")],
    )
    d = evaluate_l3_gate(p)
    assert d.passed is False
    assert d.feedback_route == "L3"
    assert any(r.request_type == "program_rework" for r in d.pending_requests)


def test_l3_ignores_warning_issues():
    p = _program(
        program_issues=[ProgramIssue(severity="warning", code="program_contradiction", message="轻微")],
    )
    d = evaluate_l3_gate(p)
    assert d.passed is True


def test_explore_when_gaps():
    p = _program(
        evidence_gaps=[EvidenceGap(gap_id="g1", dimension="project_bank", description="缺项目时序", severity="warning")],
    )
    d = evaluate_l3_gate(p)
    assert d.passed is False
    assert d.feedback_route == "EXPLORE"
    assert any(r.request_type == "evidence_gap" for r in d.pending_requests)


def test_explore_when_no_sources():
    p = _program(sources=[])
    d = evaluate_l3_gate(p)
    assert d.passed is False
    assert d.feedback_route == "EXPLORE"


def test_pass_with_sources_and_warning_gaps_resolved():
    p = _program(
        sources=[EvidenceSource(source_type="report", reference="L3:project_bank")],
        dependencies=[InterventionDependency(from_intervention_id="i1", to_intervention_id="i2")],
    )
    d = evaluate_l3_gate(p)
    assert d.passed is True
