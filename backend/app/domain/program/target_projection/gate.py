"""Planning target projection gate.

Pure function: IntentCompilationResult -> GateDecision. No I/O.

Routes:
  PASS   -> projection validated with non-empty intent
  HUMAN  -> invalid or empty typed intent (review checkpoint)
"""
from __future__ import annotations

from app.contracts.workflow.parse_result_contracts import (
    CompilationStatus,
    IntentCompilationResult,
)
from app.contracts.workflow.workflow_contracts import GateDecision


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


def evaluate_target_projection_gate(
    result: IntentCompilationResult,
    *,
    run_id: str = "",
    context_version: str = "",
) -> GateDecision:
    stage = "target_projection"
    cv = context_version or result.context_version
    gate_artifact_id = "gate-target-projection-" + (result.artifact_id or "0")

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

    return GateDecision(
        stage=stage,
        passed=True,
        feedback_route=None,
        context_version=cv,
        artifact_id=gate_artifact_id,
    )


__all__ = ["evaluate_target_projection_gate"]
