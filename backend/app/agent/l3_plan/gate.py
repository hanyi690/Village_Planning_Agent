"""G3 Program Gate evaluator for L3 PLAN.

Pure function: PlanningProgram -> GateDecision. No I/O.
Wave E delivers the evaluator; Wave M wires it into the main graph.

Decision matrix (docs/design/04_PLANNING_PIPELINE.md §8 + 07_VALIDATION_FEEDBACK.md):
  PASS    -> PARSE
  EXPLORE -> missing evidence / missing sources
  L3      -> program contradictions (rework L3)
  HUMAN   -> empty program / review checkpoint
"""
from __future__ import annotations

from typing import Any

from app.modules.schema.contracts.l3_contracts import PlanningProgram
from app.modules.schema.contracts.workflow_contracts import GateDecision, PendingRequest


def evaluate_l3_gate(
    program: PlanningProgram,
    *,
    run_id: str = "",
    context_version: str = "",
    l1_constraints: list[str] | None = None,
    l2_strategy: Any | None = None,
) -> GateDecision:
    # Reserved for Wave M: cross-checking program against L1 constraints and
    # L2 strategy. Kept deterministic and unused until a reliable detection is
    # available.
    del l1_constraints, l2_strategy

    stage = "l3"
    cv = context_version or program.context_version
    gate_artifact_id = "gate-l3-" + (program.artifact_id or "0")

    if (
        not program.interventions
        and not program.dependencies
        and not program.omissions
    ):
        return GateDecision(
            stage=stage, passed=False, feedback_route="HUMAN",
            context_version=cv, artifact_id=gate_artifact_id,
        )

    contradictions = [
        i for i in program.program_issues
        if i.code == "program_contradiction" and i.severity == "error"
    ]
    if contradictions:
        return GateDecision(
            stage=stage, passed=False, feedback_route="L3",
            pending_requests=[
                PendingRequest(
                    request_id=f"pr-l3-rework-{i.code}",
                    stage="l3",
                    request_type="program_rework",
                    context={"message": i.message, "detail": i.detail or ""},
                )
                for i in contradictions
            ],
            context_version=cv, artifact_id=gate_artifact_id,
        )

    actionable_gaps = [g for g in program.evidence_gaps if g.severity in ("warning", "error")]
    missing_sources = not program.sources
    if missing_sources or actionable_gaps:
        pending: list[PendingRequest] = []
        if missing_sources:
            pending.append(
                PendingRequest(
                    request_id="pr-l3-sources",
                    stage="explore",
                    request_type="source_lookup",
                    context={"reason": "L3 program has no evidence sources"},
                )
            )
        for g in actionable_gaps:
            pending.append(
                PendingRequest(
                    request_id=f"pr-l3-gap-{g.gap_id}",
                    stage="explore",
                    request_type="evidence_gap",
                    context={"gap_id": g.gap_id, "dimension": g.dimension, "required_fact": g.required_fact},
                )
            )
        return GateDecision(
            stage=stage, passed=False, feedback_route="EXPLORE",
            evidence_requests=[g.description for g in actionable_gaps],
            pending_requests=pending,
            context_version=cv, artifact_id=gate_artifact_id,
        )

    return GateDecision(
        stage=stage, passed=True, feedback_route=None,
        context_version=cv, artifact_id=gate_artifact_id,
    )


__all__ = ["evaluate_l3_gate"]
