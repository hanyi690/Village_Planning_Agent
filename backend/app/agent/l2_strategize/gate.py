"""G2 Strategy Gate evaluator for L2 STRATEGIZE.

Pure function: L2Strategy -> GateDecision. No I/O.
Wave D delivers the evaluator; Wave M wires it into the main graph.

Decision matrix (docs/design/04_PLANNING_PIPELINE.md §8 + 07_VALIDATION_FEEDBACK.md):
  PASS    -> L3
  EXPLORE -> missing evidence / missing sources
  L2      -> strategy contradictions (rework L2)
  HUMAN   -> empty strategy / review checkpoint
"""
from __future__ import annotations

from app.modules.schema.contracts.l2_contracts import L2Strategy
from app.modules.schema.contracts.workflow_contracts import GateDecision, PendingRequest


def evaluate_l2_gate(
    strategy: L2Strategy,
    *,
    run_id: str = "",
    context_version: str = "",
    l1_constraints: list[str] | None = None,
) -> GateDecision:
    # Reserved for Wave M: cross-checking strategy text against L1 constraints.
    # Kept deterministic and unused until a reliable detection is available.
    del l1_constraints

    stage = "l2"
    cv = context_version or strategy.context_version
    gate_artifact_id = "gate-l2-" + (strategy.artifact_id or "0")

    if (
        not strategy.development_goals
        and not strategy.implementation_priorities
        and not strategy.spatial_structure
    ):
        return GateDecision(
            stage=stage, passed=False, feedback_route="HUMAN",
            context_version=cv, artifact_id=gate_artifact_id,
        )

    contradictions = [
        i for i in strategy.strategy_issues
        if i.code == "strategy_contradiction" and i.severity == "error"
    ]
    if contradictions:
        return GateDecision(
            stage=stage, passed=False, feedback_route="L2",
            pending_requests=[
                PendingRequest(
                    request_id=f"pr-l2-rework-{i.code}",
                    stage="l2",
                    request_type="strategy_rework",
                    context={"message": i.message, "detail": i.detail or ""},
                )
                for i in contradictions
            ],
            context_version=cv, artifact_id=gate_artifact_id,
        )

    actionable_gaps = [g for g in strategy.evidence_gaps if g.severity in ("warning", "error")]
    missing_sources = not strategy.sources
    if missing_sources or actionable_gaps:
        pending: list[PendingRequest] = []
        if missing_sources:
            pending.append(
                PendingRequest(
                    request_id="pr-l2-sources",
                    stage="explore",
                    request_type="source_lookup",
                    context={"reason": "L2 strategy has no evidence sources"},
                )
            )
        for g in actionable_gaps:
            pending.append(
                PendingRequest(
                    request_id=f"pr-l2-gap-{g.gap_id}",
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


__all__ = ["evaluate_l2_gate"]
