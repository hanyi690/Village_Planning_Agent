"""G3 Program Gate evaluator for L3 PLAN.

Pure function: PlanningProgram -> GateDecision. No I/O.
Wave E delivers the evaluator; Wave M wires it into the main graph.

Decision matrix (docs/design/01_CONTRACTS_AND_INVARIANTS.md gate semantics + docs/design/03_PLANNING_EXECUTION.md):
  PASS    -> TARGET_PROJECTION
  EXPLORE -> missing evidence / missing sources
  L3      -> program contradictions (rework L3)
  HUMAN   -> empty program / review checkpoint
"""
from __future__ import annotations

from typing import Any

from app.domain.program.classification import classification_review_targets
from app.contracts.artifacts.classification_ref import classification_code_names
from app.contracts.domain.l3_contracts import PlanningProgram
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
        and not program.dependencies
        and not program.omissions
    )
    has_spatial_strategy = (
        l2_strategy is not None
        and isinstance(getattr(l2_strategy, "spatial_structure", ""), str)
        and bool(l2_strategy.spatial_structure.strip())
    )

    contradictions = [
        issue
        for issue in program.program_issues
        if issue.severity == "error"
        and issue.code != "classification_decision_required"
    ]
    # A program may contain both admitted spatial interventions and claims
    # that are intentionally diagnostic-only (missing typed parameters,
    # package identity, or evidence lineage).  Those rejected claims must
    # remain visible in the gate diagnostics, but they must not suppress an
    # independently admissible subset.  If there is no admissible subset,
    # retain the strict L3 rework boundary.
    blocking_contradictions = [
        issue
        for issue in contradictions
        if not (
            issue.code in {"claim_admission_incomplete", "claim_not_executable"}
            and program.interventions
        )
    ]
    if blocking_contradictions:
        return GateDecision(
            stage=stage, passed=False, feedback_route="L3",
            pending_requests=[
                PendingRequest(
                    request_id=f"pr-l3-rework-{i.dimension_key or 'program'}-{i.code}",
                    stage="l3",
                    request_type="program_rework",
                    context={
                        "dimension_key": i.dimension_key,
                        "claim_id": i.claim_id,
                        "message": i.message,
                        "detail": i.detail or "",
                    },
                )
                for i in blocking_contradictions
            ],
            context_version=cv, artifact_id=gate_artifact_id,
        )

    if not program.interventions and program.claims and not has_spatial_strategy:
        return GateDecision(
            stage=stage,
            passed=False,
            feedback_route="HUMAN",
            pending_requests=[
                PendingRequest(
                    request_id="pr-l3-claim-only-review",
                    stage="l3",
                    request_type="program_review",
                    context={
                        "message": "L3 claims were preserved but none were admitted as spatial interventions",
                        "claim_count": len(program.claims),
                        "reason_code": "zero_spatial_interventions",
                    },
                )
            ],
            route_reason="zero_spatial_interventions",
            context_version=cv,
            artifact_id=gate_artifact_id,
        )

    if empty_program and not has_spatial_strategy:
        pending: list[PendingRequest] = []
        if l1_constraints:
            pending.append(
                PendingRequest(
                    request_id="pr-l3-empty-l1",
                    stage="l3",
                    request_type="program_rework",
                    context={
                        "message": "L3 produced an empty program but L1 constraints are present",
                        "l1_constraints_present": len(l1_constraints),
                    },
                )
            )
        return GateDecision(
            stage=stage, passed=False, feedback_route="HUMAN",
            pending_requests=pending,
            context_version=cv, artifact_id=gate_artifact_id,
        )

    if has_spatial_strategy and not program.interventions:
        return GateDecision(
            stage=stage, passed=False, feedback_route="L3",
            pending_requests=[
                PendingRequest(
                    request_id="pr-l3-strategy-orphan",
                    stage="l3",
                    request_type="program_rework",
                    context={
                        "message": "L2 spatial structure defined but L3 produced zero interventions",
                        "detail": l2_strategy.spatial_structure.strip()[:200],
                    },
                )
            ],
            context_version=cv, artifact_id=gate_artifact_id,
        )

    # Error is a contract severity, not an allow-listed log label.  Passing an
    # unknown error code allowed malformed L3 claim sets to reach EXECUTE and
    # multiply into thousands of spatial conflicts.  Semantic repair may
    # explicitly downgrade a resolved normalization/audit item; every error
    # that remains must route back to L3.
    #
    # ``classification_decision_required`` is deliberately excluded: it is a
    # HUMAN-boundary decision (see below), not a contradiction of the source
    # program.  The assembler records it at error severity so EXECUTE can never
    # run an unclassified polygon target, but treating it as a rework
    # contradiction would make the classification branch unreachable and loop
    # the graph at L3 forever.
    if blocking_contradictions:
        return GateDecision(
            stage=stage, passed=False, feedback_route="L3",
            pending_requests=[
                PendingRequest(
                    request_id=f"pr-l3-rework-{i.dimension_key or 'program'}-{i.code}",
                    stage="l3",
                    request_type="program_rework",
                    context={
                        "dimension_key": i.dimension_key,
                        "message": i.message,
                        "detail": i.detail or "",
                    },
                )
                for i in blocking_contradictions
            ],
            context_version=cv, artifact_id=gate_artifact_id,
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
    missing_sources = not program.sources and not program.interventions
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
