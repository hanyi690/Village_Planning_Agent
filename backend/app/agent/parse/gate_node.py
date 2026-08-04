"""PARSE gate node - 4-route evaluator (Hybrid routing).

Pure function: IntentCompilationResult -> GateDecision. No I/O. Mirrors
``evaluate_l3_gate`` (app.agent.l3_plan.gate) with stage="parse".

Routes:
  PASS   -> compilation validated with non-empty intent
  REPAIR -> needs_repair with <= 5 patches (localized fix)
  REVISE -> needs_repair with > 5 patches (structural rework)
  HUMAN  -> needs_review or empty typed intent (review checkpoint)
"""
from __future__ import annotations

from app.modules.schema.contracts.parse_result_contracts import (
    CompilationStatus,
    IntentCompilationResult,
)
from app.modules.schema.contracts.workflow_contracts import GateDecision, PendingRequest

_REPAIR_PATCH_LIMIT = 5


def _is_empty_intent(result: IntentCompilationResult) -> bool:
    intent = result.typed_intent
    if intent is None:
        return True
    return not (
        intent.project_targets
        or intent.facilities
        or intent.road_targets
        or intent.zone_targets
    )


def evaluate_parse_gate(
    result: IntentCompilationResult,
    *,
    run_id: str = "",
    context_version: str = "",
) -> GateDecision:
    stage = "parse"
    cv = context_version or result.context_version
    gate_artifact_id = "gate-parse-" + (result.artifact_id or "0")

    if result.compilation_status == CompilationStatus.NEEDS_REVIEW or _is_empty_intent(
        result
    ):
        return GateDecision(
            stage=stage,
            passed=False,
            feedback_route="HUMAN",
            context_version=cv,
            artifact_id=gate_artifact_id,
        )

    if result.compilation_status == CompilationStatus.NEEDS_REPAIR:
        patch_count = len(result.patches)
        if patch_count > _REPAIR_PATCH_LIMIT:
            return GateDecision(
                stage=stage,
                passed=False,
                feedback_route="REVISE",
                pending_requests=[
                    PendingRequest(
                        request_id="pr-parse-revise",
                        stage="parse",
                        request_type="structural_rework",
                        context={
                            "reason": "more than 5 patches - structural rework",
                            "patch_count": patch_count,
                        },
                    )
                ],
                context_version=cv,
                artifact_id=gate_artifact_id,
            )
        return GateDecision(
            stage=stage,
            passed=False,
            feedback_route="REPAIR",
            pending_requests=[
                PendingRequest(
                    request_id="pr-parse-repair",
                    stage="parse",
                    request_type="localized_fix",
                    context={
                        "reason": "fewer than 6 patches - localized fix",
                        "patch_count": patch_count,
                    },
                )
            ],
            context_version=cv,
            artifact_id=gate_artifact_id,
        )

    return GateDecision(
        stage=stage,
        passed=True,
        feedback_route=None,
        context_version=cv,
        artifact_id=gate_artifact_id,
    )


__all__ = ["evaluate_parse_gate"]
