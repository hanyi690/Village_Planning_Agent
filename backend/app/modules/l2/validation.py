"""G2 Strategy Gate evaluator for L2 STRATEGIZE.

Pure function: L2Strategy -> GateDecision. No I/O.
Wave D delivers the evaluator; Wave M wires it into the main graph.

Decision matrix (docs/design/01_CONTRACTS_AND_INVARIANTS.md gate semantics + docs/design/02_PLANNING_COGNITION.md):
  PASS    -> L3
  PASS    -> usable partial strategy, with unresolved evidence retained
  L2      -> strategy contradictions (rework L2)
  EXPLORE -> optional evidence recovery when explicitly requested
  HUMAN   -> empty strategy / review checkpoint
"""
from __future__ import annotations

from app.contracts.l2.l2_contracts import L2Strategy
from app.contracts.workflow.recovery_pointer import RecoveryPointer
from app.contracts.workflow.workflow_contracts import GateDecision, PendingRequest


def evaluate_l2_gate(
    strategy: L2Strategy,
    *,
    run_id: str = "",
    context_version: str = "",
    l1_constraints: list[str] | None = None,
) -> GateDecision:
    stage = "l2"
    cv = context_version or strategy.context_version
    gate_artifact_id = "gate-l2-" + (strategy.artifact_id or "0")

    if (
        not strategy.development_goals
        and not strategy.implementation_priorities
        and not strategy.spatial_structure
    ):
        pending: list[PendingRequest] = []
        if l1_constraints:
            pending.append(
                PendingRequest(
                    request_id="pr-l2-empty-l1",
                    stage="l2",
                    request_type="strategy_rework",
                    context={
                        "message": "L2 produced an empty strategy but L1 constraints are present",
                        "l1_constraints_present": len(l1_constraints),
                    },
                )
            )
        return GateDecision(
            stage=stage, passed=False, feedback_route="HUMAN",
            pending_requests=pending,
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

    # A gap without a required fact is advisory model text, not an evidence
    # request. Only typed gaps with an explicit missing fact are actionable.
    def _actionable_gap(g: object) -> bool:
        required = str(getattr(g, "required_fact", "") or "").strip()
        return bool(required)

    actionable_gaps = [
        g for g in strategy.evidence_gaps
        if g.severity in ("warning", "error") and _actionable_gap(g)
    ]
    missing_sources = not strategy.sources and not strategy.development_goals
    if missing_sources or actionable_gaps:
        pending: list[PendingRequest] = []
        if missing_sources:
            recovery = RecoveryPointer(
                item_id="l2-sources",
                item_kind="artifact_input",
                source_stage="l2",
                return_stage="l2",
                source_artifact_key="l2_strategy",
                source_artifact_ref=str(strategy.artifact_id or ""),
                source_input_refs=["artifact:l1_snapshot"],
                missing_requirements=["l2_evidence_source"],
                expected_artifact_key="l2_strategy",
                reason_code="l2_sources_missing",
            )
            pending.append(
                PendingRequest(
                    request_id="pr-l2-sources",
                    stage="explore",
                    request_type="source_lookup",
                    context={"reason": "L2 strategy has no evidence sources"},
                    recovery=recovery,
                )
            )
        for g in actionable_gaps:
            producer = next(
                (
                    decision
                    for decision in strategy.decision_sets
                    if any(item.gap_id == g.gap_id for item in decision.evidence_gaps)
                ),
                None,
            )
            producer_dimension = str(
                getattr(producer, "dimension_key", "") or g.dimension or "l2"
            ).strip()
            source_input_refs = [
                "artifact:l1_snapshot",
                *list(getattr(producer, "source_refs", None) or []),
            ]
            recovery = RecoveryPointer(
                item_id=g.gap_id,
                item_kind="artifact_input",
                source_stage="l2",
                return_stage="l2",
                source_artifact_key="l2_strategy",
                source_artifact_ref=str(strategy.artifact_id or ""),
                source_input_refs=source_input_refs,
                missing_requirements=[str(g.required_fact).strip()],
                expected_artifact_key="l2_strategy",
                reason_code="l2_evidence_gap",
            )
            pending.append(
                PendingRequest(
                    request_id=f"pr-l2-gap-{g.gap_id}",
                    stage="explore",
                    request_type="evidence_gap",
                    context={
                        "gap_id": g.gap_id,
                        "dimension": g.dimension,
                        "producer_dimension": producer_dimension,
                        "producer_stage": "l2",
                        "required_fact": g.required_fact,
                        "source_input_refs": source_input_refs,
                        "return_stage": "l2",
                        "expected_artifact_key": "l2_strategy",
                    },
                    recovery=recovery,
                )
            )
        # A usable partial strategy may advance with an explicit evidence
        # deficit.  Keep every recovery request on the gate so the missing
        # input remains visible to downstream stages; only the structural
        # failures handled above block L2.
        return GateDecision(
            stage=stage, passed=True, feedback_route=None,
            evidence_requests=[g.description for g in actionable_gaps],
            pending_requests=pending,
            context_version=cv,
            artifact_id=gate_artifact_id,
            route_reason=(
                "passed_with_unresolved_evidence"
                if actionable_gaps or missing_sources
                else "checks_passed"
            ),
        )

    return GateDecision(
        stage=stage, passed=True, feedback_route=None,
        context_version=cv, artifact_id=gate_artifact_id,
    )


__all__ = ["evaluate_l2_gate"]
