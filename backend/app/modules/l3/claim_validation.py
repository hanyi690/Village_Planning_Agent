"""G3 Program Gate evaluator for L3 PLAN.

Pure function: PlanningProgram -> GateDecision. No I/O.
Wave E delivers the evaluator; Wave M wires it into the main graph.

Decision matrix (docs/design/01_CONTRACTS_AND_INVARIANTS.md gate semantics + docs/design/03_PLANNING_INTENT.md):
  PASS    -> TARGET_PROJECTION
  PASS    -> usable partial program, with unresolved evidence retained
  L3      -> program contradictions (rework L3)
  EXPLORE -> optional evidence recovery when explicitly requested
  HUMAN   -> empty program / review checkpoint
"""
from __future__ import annotations

from typing import Any

from app.modules.l3.classification import classification_review_targets
from app.contracts.artifacts.classification_ref import classification_code_names
from app.contracts.l3.l3_contracts import PlanningProgram
from app.contracts.workflow.workflow_contracts import GateDecision, PendingRequest


def evaluate_l3_gate(
    program: PlanningProgram,
    *,
    run_id: str = "",
    context_version: str = "",
    l1_constraints: list[str] | None = None,
    l2_strategy: Any | None = None,
) -> GateDecision:
    stage = "l3"
    cv = context_version or program.context_version
    gate_artifact_id = "gate-l3-" + (program.artifact_id or "0")

    empty_program = (
        not program.interventions
        and not program.claims
        and not program.pending_grounding_claims
        and not program.dependencies
        and not program.omissions
    )
    has_spatial_strategy = (
        l2_strategy is not None
        and isinstance(getattr(l2_strategy, "spatial_structure", ""), str)
        and bool(l2_strategy.spatial_structure.strip())
    )

    if empty_program:
        return GateDecision(
            stage=stage,
            passed=False,
            feedback_route="HUMAN",
            pending_requests=[
                PendingRequest(
                    request_id="pr-l3-empty-program",
                    stage="l3",
                    request_type="program_input_missing",
                    context={
                        "message": "L3 produced no claims, interventions, dependencies, or omissions",
                        "l2_strategy_present": l2_strategy is not None,
                    },
                )
            ],
            context_version=cv,
            artifact_id=gate_artifact_id,
            route_reason="empty_program",
        )

    from app.modules.l3.failure_scope import (
        ClaimDependencyGraph,
        FailureScope,
        classify_failure_scope,
    )

    dependency_graph = ClaimDependencyGraph.from_program(program)
    blocking_contradictions: list[Any] = []
    for issue in program.program_issues:
        if issue.severity != "error" or issue.code == "classification_decision_required":
            continue
        decision = classify_failure_scope(issue, dependency_graph)
        if not decision.blocking:
            continue
        if (
            decision.scope in {FailureScope.CLAIM, FailureScope.RELATION}
            and not decision.dependency_scope
            and not (
                admission_without_spatial_output
            )
        ):
            # The claim was quarantined before admission, so an unrelated
            # admitted intervention remains eligible for projection.
            continue
        blocking_contradictions.append((issue, decision))
    if blocking_contradictions:
        return GateDecision(
            stage=stage,
            passed=False,
            feedback_route="L3",
            pending_requests=[
                PendingRequest(
                    request_id=f"pr-l3-rework-{issue.dimension_key or 'program'}-{issue.code}",
                    stage="l3",
                    request_type="program_rework",
                    context={
                        "dimension_key": issue.dimension_key,
                        "claim_id": issue.claim_id,
                        "message": issue.message,
                        "detail": issue.detail or "",
                        "root_issue_id": decision.root_issue_id,
                        "failure_scope": decision.scope.value,
                        "dependency_scope": sorted(decision.dependency_scope),
                    },
                )
                for issue, decision in blocking_contradictions
            ],
            context_version=cv,
            artifact_id=gate_artifact_id,
        )

    if program.claims and not program.interventions:
        from app.contracts.workflow.recovery_pointer import RecoveryPointer

        spatial_claims = [
            claim
            for claim in program.claims
            if claim.planning_role == "spatial_intervention"
        ]
        claims_for_review = spatial_claims or list(program.claims)
        disposition_by_claim = {
            item.claim_id: item
            for item in program.claim_dispositions
        }
        pending_requests = []
        for claim in claims_for_review:
            disposition = disposition_by_claim.get(claim.claim_id)
            missing_requirements = list(
                getattr(disposition, "missing_requirements", None) or []
            )
            recovery = RecoveryPointer(
                item_id=claim.claim_id,
                item_kind="claim",
                source_stage="l3",
                return_stage="l3",
                source_artifact_key="planning_program",
                source_artifact_ref=str(program.artifact_id or ""),
                source_input_refs=[
                    str(program.l1_snapshot_ref or ""),
                    *list(claim.source_fact_refs),
                    *list(claim.source_refs),
                    *list(claim.location_hints),
                ],
                missing_requirements=missing_requirements,
                expected_artifact_key="planning_program",
                reason_code="zero_spatial_interventions",
            )
            pending_requests.append(
                PendingRequest(
                    request_id=f"pr-l3-claim-{claim.claim_id}",
                    stage="l3",
                    request_type="claim_grounding_input",
                    context={
                        "message": (
                            "Resolve this claim's missing semantic or source inputs "
                            "before TARGET_PROJECTION"
                        ),
                        "claim_id": claim.claim_id,
                        "dimension_key": claim.dimension_key,
                        "missing_requirements": missing_requirements,
                        "source_input_refs": recovery.source_input_refs,
                        "expected_artifact_key": "planning_program",
                    },
                    recovery=recovery,
                )
            )
        return GateDecision(
            stage=stage,
            passed=True,
            feedback_route=None,
            pending_requests=pending_requests,
            context_version=cv,
            artifact_id=gate_artifact_id,
            route_reason="passed_with_pending_claims",
        )

    classification_targets = classification_review_targets(program)
    if classification_targets:
        target_ids = [item["target_id"] for item in classification_targets]
        catalog = classification_code_names("ghytbm") or {}
        return GateDecision(
            stage=stage,
            passed=False,
            feedback_route="HUMAN",
            pending_requests=[
                PendingRequest(
                    request_id="pr-l3-classification-decisions",
                    stage="l3",
                    request_type="classification_decision_required",
                    context={
                        "message": "空间 polygon/parcel 目标必须先获得显式规划分类决定",
                        "target_ids": target_ids,
                        "targets": classification_targets,
                        "recommended_code_system": "ghytbm",
                        "classification_catalog": {
                            "ghytbm": [
                                {"code": code, "canonical_name": name}
                                for code, name in sorted(catalog.items())
                            ]
                        },
                        "decision_contract": "ClassificationDecision",
                        "instruction": (
                            "只能从声明的闭集编码中选择；不得填写由现状 dlbm、名称或 crosswalk 推导的编码。"
                        ),
                    },
                )
            ],
            context_version=cv,
            artifact_id=gate_artifact_id,
            route_reason="classification_decision_required",
        )

    actionable_gaps = [g for g in program.evidence_gaps if g.severity in ("warning", "error")]
    missing_sources = not program.sources and empty_program
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
        # A program may be delivered with explicit unresolved evidence.  The
        # gap and its recovery request stay attached to the program, while
        # TARGET_PROJECTION decides whether the affected target is pending or
        # deferred.  Structural claim failures above still block L3.
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


__all__ = ["evaluate_l3_gate"]
