"""G1 Evidence Gate evaluator for L1 OBSERVE.

Pure function: L1Snapshot -> GateDecision. No I/O.
Wave B delivers the evaluator; Wave M wires it into the main graph.

Decision matrix (docs/design/01_CONTRACTS_AND_INVARIANTS.md gate semantics + docs/design/01_CONTRACTS_AND_INVARIANTS.md):
  PASS    -> L2 STRATEGIZE
  PASS    -> usable partial snapshot, with unresolved evidence retained
  L1      -> fact contradictions (rework L1)
  EXPLORE -> optional evidence recovery when explicitly requested
  HUMAN   -> empty snapshot / review checkpoint
"""
from __future__ import annotations

from app.contracts.l1.l1_contracts import L1Snapshot
from app.contracts.workflow.recovery_pointer import RecoveryPointer
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

    incomplete_dimensions = [
        issue for issue in snapshot.issues
        if issue.code == "dimension_product_incomplete" and issue.severity == "error"
    ]
    if incomplete_dimensions:
        pending_requests = []
        for issue in incomplete_dimensions:
            dimension = issue.message.rsplit(":", 1)[-1].strip() or "unknown"
            recovery = RecoveryPointer(
                item_id=dimension,
                item_kind="artifact_input",
                source_stage="l1",
                return_stage="l1",
                source_artifact_key=f"l1_dimension__{dimension}",
                source_artifact_ref="",
                source_input_refs=[],
                missing_requirements=["completed typed L1 dimension product"],
                expected_artifact_key=f"l1_dimension__{dimension}",
                reason_code="dimension_product_incomplete",
            )
            pending_requests.append(PendingRequest(
                request_id=f"pr-l1-dimension-{dimension}",
                stage="l1",
                request_type="dimension_product_recovery",
                context={
                    "producer_dimension": dimension,
                    "message": issue.message,
                    "detail": issue.detail or "",
                },
                recovery=recovery,
            ))
        return GateDecision(
            stage=stage,
            passed=False,
            feedback_route="HUMAN",
            pending_requests=pending_requests,
            context_version=cv,
            artifact_id=gate_artifact_id,
            route_reason="typed_dimension_product_incomplete",
        )

    if not snapshot.facts and not snapshot.constraints and not snapshot.sources:
        return GateDecision(
            stage=stage, passed=False, feedback_route="HUMAN",
            context_version=cv, artifact_id=gate_artifact_id,
        )

    rework_issues = [
        i for i in snapshot.issues
        if i.code in {
            "fact_contradiction",
            "spatial_semantic_admission_failed",
        }
        and i.severity == "error"
    ]
    if rework_issues:
        return GateDecision(
            stage=stage, passed=False, feedback_route="L1",
            pending_requests=[
                PendingRequest(
                    request_id=f"pr-l1-rework-{index}-{i.code}",
                    stage="l1",
                    request_type="fact_rework",
                    context={"message": i.message, "detail": i.detail or ""},
                )
                for index, i in enumerate(rework_issues)
            ],
            context_version=cv, artifact_id=gate_artifact_id,
            route_reason="l1_semantic_rework_required",
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
    human_gaps = [
        gap
        for gap in actionable_gaps
        if gap.outcome_status in {"human_required", "not_available"}
        or (
            gap.outcome_status in {"partial", "insufficient", "failed"}
            and not gap.recoverable
        )
        or gap.coverage_stop_reason == "human_required"
    ]
    if human_gaps:
        return GateDecision(
            stage=stage,
            passed=False,
            feedback_route="HUMAN",
            evidence_requests=[gap.description for gap in human_gaps],
            pending_requests=[
                PendingRequest(
                    request_id=f"pr-l1-human-{index}-{gap.gap_id}",
                    stage="l1",
                    request_type="evidence_human_confirmation",
                    context={
                        "gap_id": gap.gap_id,
                        "subject_ref": gap.subject_ref,
                        "requirement_id": gap.requirement_id,
                        "outcome_status": gap.outcome_status,
                        "reason_codes": list(gap.reason_codes),
                        "candidate_total": gap.candidate_total,
                        "candidate_identity_total": (
                            gap.candidate_identity_total
                        ),
                        "ambiguity_status": gap.ambiguity_status,
                        "coverage_stop_reason": gap.coverage_stop_reason,
                        "recovery_action": gap.recovery_action,
                    },
                )
                for index, gap in enumerate(human_gaps)
            ],
            context_version=cv,
            artifact_id=gate_artifact_id,
            route_reason="l1_evidence_requires_human_confirmation",
        )
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
        # A source gap is actionable at L1.  Keep the typed recovery requests,
        # but fail the gate so L2 cannot consume a partial snapshot as if it
        # were a complete observation product.  The normal EXPLORE route
        # performs bounded retrieval immediately and re-runs only affected
        # dimensions.
        return GateDecision(
            stage=stage, passed=False, feedback_route="EXPLORE",
            evidence_requests=[g.description for g in actionable_gaps],
            pending_requests=pending,
            context_version=cv,
            artifact_id=gate_artifact_id,
            route_reason=(
                "evidence_gap_requires_l1_recovery"
                if actionable_gaps or missing_sources
                else "checks_passed"
            ),
        )

    return GateDecision(
        stage=stage, passed=True, feedback_route=None,
        context_version=cv, artifact_id=gate_artifact_id,
    )


__all__ = ["evaluate_l1_gate"]
