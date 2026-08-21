"""G1 Evidence Gate evaluator for L1 OBSERVE.

Pure function: L1Snapshot -> GateDecision. No I/O.
Wave B delivers the evaluator; Wave M wires it into the main graph.

Decision matrix (docs/design/04_PLANNING_PIPELINE.md §8 + 07_VALIDATION_FEEDBACK.md):
  PASS    -> L2 STRATEGIZE
  EXPLORE -> missing evidence / missing sources
  L1      -> fact contradictions (rework L1)
  HUMAN   -> empty snapshot / review checkpoint
"""
from __future__ import annotations

from app.contracts.domain.l1_contracts import L1Snapshot
from app.contracts.workflow.workflow_contracts import GateDecision, PendingRequest


def _unverified_quantitative_facts(snapshot: L1Snapshot) -> list[str]:
    """Find source-feature counts that cannot identify their source snapshot."""
    refs: list[str] = []
    for fact in snapshot.fact_records:
        if fact.counting_basis != "source_feature" or fact.value is None:
            continue
        if not fact.source_snapshot_ref or not fact.source_feature_ids:
            refs.append(fact.fact_id)
    return refs


def evaluate_l1_gate(
    snapshot: L1Snapshot,
    *,
    run_id: str = "",
    context_version: str = "",
) -> GateDecision:
    stage = "l1"
    cv = context_version or snapshot.context_version
    gate_artifact_id = "gate-l1-" + (snapshot.artifact_id or "0")

    if not snapshot.facts and not snapshot.constraints and not snapshot.sources:
        return GateDecision(
            stage=stage, passed=False, feedback_route="HUMAN",
            context_version=cv, artifact_id=gate_artifact_id,
        )

    contradictions = [
        i for i in snapshot.issues
        if i.code == "fact_contradiction" and i.severity == "error"
    ]
    if contradictions:
        return GateDecision(
            stage=stage, passed=False, feedback_route="L1",
            pending_requests=[
                PendingRequest(
                    request_id=f"pr-l1-rework-{i.code}",
                    stage="l1",
                    request_type="fact_rework",
                    context={"message": i.message, "detail": i.detail or ""},
                )
                for i in contradictions
            ],
            context_version=cv, artifact_id=gate_artifact_id,
        )

    unverified_counts = _unverified_quantitative_facts(snapshot)
    if unverified_counts:
        return GateDecision(
            stage=stage,
            passed=False,
            feedback_route="EXPLORE",
            evidence_requests=[
                "补齐定量事实的 source collection、snapshot 和 source feature IDs",
            ],
            pending_requests=[
                PendingRequest(
                    request_id="pr-l1-quantitative-lineage",
                    stage="explore",
                    request_type="evidence_gap",
                    context={
                        "reason": "quantitative source-feature facts lack valid lineage",
                        "fact_refs": unverified_counts[:12],
                    },
                )
            ],
            context_version=cv,
            artifact_id=gate_artifact_id,
        )

    actionable_gaps = [g for g in snapshot.evidence_gaps if g.severity in ("warning", "error")]
    missing_sources = not snapshot.sources and not snapshot.facts
    if missing_sources or actionable_gaps:
        pending: list[PendingRequest] = []
        if missing_sources:
            pending.append(
                PendingRequest(
                    request_id="pr-l1-sources",
                    stage="explore",
                    request_type="source_lookup",
                    context={"reason": "L1 snapshot has no evidence sources"},
                )
            )
        for g in actionable_gaps:
            pending.append(
                PendingRequest(
                    request_id=f"pr-l1-gap-{g.gap_id}",
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


__all__ = ["evaluate_l1_gate"]
