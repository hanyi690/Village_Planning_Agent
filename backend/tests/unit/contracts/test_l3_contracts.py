"""L3 PLAN contract tests - Wave E enrichment."""

from __future__ import annotations

import pytest

from app.modules.schema.contracts.evidence_contracts import EvidenceSource
from app.modules.schema.contracts.l1_contracts import EvidenceGap
from app.modules.schema.contracts.l3_contracts import (
    InterventionDependency,
    L3ProgramFragment,
    PlanningIntervention,
    PlanningProgram,
    ProgramIssue,
)
from app.modules.schema.contracts.provenance import Provenance


def test_planning_program_enriched_fields():
    p = PlanningProgram(
        interventions=[PlanningIntervention(intervention_id="i1", name="项目A")],
        dependencies=[InterventionDependency(from_intervention_id="i1", to_intervention_id="i2")],
        omissions=["生态廊道"],
        evidence_gaps=[EvidenceGap(gap_id="g1", dimension="project_bank", description="缺项目时序", severity="warning")],
        sources=[EvidenceSource(source_type="report", reference="L3:project_bank")],
        program_issues=[ProgramIssue(severity="error", code="program_contradiction", message="项目重叠")],
        dimension_provenance=[Provenance(source="l3_plan", run_id="r1", module="l3_plan")],
    )
    assert p.evidence_gaps[0].gap_id == "g1"
    assert p.sources[0].source_type == "report"
    assert p.program_issues[0].code == "program_contradiction"
    assert p.dimension_provenance[0].run_id == "r1"
    # legacy fields preserved
    assert p.interventions[0].name == "项目A"
    assert p.omissions == ["生态廊道"]


def test_l3_program_fragment_fields():
    f = L3ProgramFragment(
        dimension_key="project_bank",
        interventions=[PlanningIntervention(intervention_id="i1", name="项目A")],
        dependencies=[InterventionDependency(from_intervention_id="i1", to_intervention_id="i2")],
        evidence_gaps=[EvidenceGap(gap_id="g", dimension="d", description="x")],
        program_issues=[ProgramIssue(code="c", message="m")],
        omissions=["o"],
    )
    assert f.dimension_key == "project_bank"
    assert f.interventions[0].name == "项目A"
    assert f.dependencies[0].from_intervention_id == "i1"
    assert f.evidence_gaps[0].gap_id == "g"
    assert f.program_issues[0].code == "c"
    assert f.omissions == ["o"]
    assert f.provenance is None
    assert f.trace is None


def test_program_issue_mirrors_stage_issue():
    i = ProgramIssue(severity="error", code="program_contradiction", message="x", detail="detail")
    assert i.stage == "l3"
    assert i.severity == "error"
    assert i.code == "program_contradiction"
    assert i.detail == "detail"


def test_planning_program_legacy_construction():
    p = PlanningProgram(
        interventions=[PlanningIntervention(intervention_id="i1", name="x")],
        dependencies=[InterventionDependency(from_intervention_id="i1", to_intervention_id="i2")],
        omissions=["o"],
    )
    assert p.interventions[0].name == "x"
    assert p.dependencies[0].to_intervention_id == "i2"
    assert p.omissions == ["o"]
