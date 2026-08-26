"""L3 classification gate: decision-required issues must reach the HUMAN branch.

`classification_decision_required` is a HUMAN-boundary decision, not a program
contradiction.  Treating it as an L3 rework contradiction made the dedicated
classification branch unreachable and looped the graph at L3 forever.
"""

from __future__ import annotations

import hashlib

import pytest

from app.contracts.domain.l3_contracts import (
    PlanningIntervention,
    PlanningProgram,
    ProgramIssue,
)
from app.domain.program.classification import (
    classification_review_targets,
    revise_program_with_decisions,
)
from app.domain.program.gate import evaluate_l3_gate
from app.workflow.root_graph import prepare_human_review


def _polygon_intervention(
    target_id: str,
    *,
    name: str = "一般农业区",
) -> PlanningIntervention:
    return PlanningIntervention(
        intervention_id=target_id,
        target_id=target_id,
        name=name,
        category="zone",
        execution_mode="spatial",
        expected_output_kind="polygon",
        claim_refs=[target_id.split(":")[-1]],
        evidence_refs=[f"claim:{target_id}"],
    )


def _classification_issue(target_id: str) -> ProgramIssue:
    return ProgramIssue(
        stage="synthesize",
        severity="error",
        code="classification_decision_required",
        message=f"spatial target {target_id} requires an explicit ClassificationDecision",
        detail=target_id,
    )


def _sha(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def test_classification_issue_routes_human_not_l3_rework() -> None:
    program = PlanningProgram(
        interventions=[
            _polygon_intervention("land_use_planning:claim:FA-02"),
            _polygon_intervention("land_use_planning:claim:LU-01"),
        ],
        program_issues=[
            _classification_issue("land_use_planning:claim:FA-02"),
            _classification_issue("land_use_planning:claim:LU-01"),
        ],
    )

    gate = evaluate_l3_gate(program)

    assert gate.passed is False
    assert gate.feedback_route == "HUMAN"
    assert len(gate.pending_requests) == 1
    request = gate.pending_requests[0]
    assert request.request_type == "classification_decision_required"
    assert request.context["target_ids"] == [
        "land_use_planning:claim:FA-02",
        "land_use_planning:claim:LU-01",
    ]


def test_real_contradiction_still_routes_l3_even_with_classification_targets() -> None:
    program = PlanningProgram(
        interventions=[_polygon_intervention("land_use_planning:claim:FA-02")],
        program_issues=[
            _classification_issue("land_use_planning:claim:FA-02"),
            ProgramIssue(
                stage="synthesize",
                severity="error",
                code="program_semantic_contradiction",
                message="two admitted spatial targets have incompatible hard constraints",
            ),
        ],
    )

    gate = evaluate_l3_gate(program)

    assert gate.feedback_route == "L3"
    assert all(request.request_type == "program_rework" for request in gate.pending_requests)


def test_classification_targets_preserve_non_generic_lineage_as_evidence() -> None:
    intervention = _polygon_intervention("land_use_planning:claim:FA-02").model_copy(
        update={
            "evidence_refs": [],
            "source_fact_refs": ["l1:fact:FA-02"],
            "source_refs": ["source:land-use:FA-02"],
        }
    )
    targets = classification_review_targets(PlanningProgram(interventions=[intervention]))

    assert targets[0]["evidence_refs"] == [
        "l1:fact:FA-02",
        "source:land-use:FA-02",
    ]


def test_complete_decisions_flip_gate_to_pass() -> None:
    program = PlanningProgram(
        interventions=[_polygon_intervention("land_use_planning:claim:FA-02")],
        program_issues=[_classification_issue("land_use_planning:claim:FA-02")],
    )

    targets = classification_review_targets(program)
    assert [item["target_id"] for item in targets] == ["land_use_planning:claim:FA-02"]

    decisions = [
        {
            "target_id": item["target_id"],
            "code_system": "appendix5",
            "selected_code": "1100",
            "candidate_codes": ["1100"],
            "status": "resolved",
            "rationale": "regression stub",
            "evidence_refs": list(item.get("evidence_refs") or []),
        }
        for item in targets
    ]
    revised, applied = revise_program_with_decisions(program, decisions)

    assert applied == ["land_use_planning:claim:FA-02"]
    assert classification_review_targets(revised) == []
    gate = evaluate_l3_gate(revised)
    assert gate.passed is True
    assert gate.feedback_route is None


@pytest.mark.asyncio
async def test_prepare_human_review_keeps_typed_classification_request(monkeypatch) -> None:
    program = PlanningProgram(
        interventions=[_polygon_intervention("land_use_planning:claim:FA-02")],
        program_issues=[_classification_issue("land_use_planning:claim:FA-02")],
    )
    gate = evaluate_l3_gate(program)
    monkeypatch.setattr(
        "app.workflow.root_graph.load_root_gate",
        lambda _state, _stage: gate,
    )

    prepared = await prepare_human_review({
        "phase": "layer3",
        "l3_gate": gate.model_dump(mode="json"),
    })

    assert prepared["paused_stage"] == "l3"
    assert [
        item["request_type"] for item in prepared["human_review_items"]
    ] == ["classification_decision_required"]
