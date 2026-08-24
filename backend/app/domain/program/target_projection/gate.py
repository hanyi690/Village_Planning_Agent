"""Planning target projection gate.

Pure function: IntentCompilationResult -> GateDecision. No I/O.

Routes:
  PASS   -> projection validated with non-empty intent
  L3     -> non-admission semantic error requiring compiler rework
  HUMAN  -> unresolved admission, needs-review, or empty intent
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
        intent.site_area_targets
        or intent.facilities
        or intent.road_targets
        or intent.linear_targets
        or intent.zone_targets
    )


def _is_admission_diagnostic(diagnostic: object) -> bool:
    """Return whether a diagnostic means TARGET admission is not trustworthy."""
    code = str(getattr(diagnostic, "code", "") or "").strip().upper()
    return code.startswith("INTERVENTION_ADMISSION_") or code in {
        "INTERVENTION_NOT_ADMITTED",
    }


def evaluate_target_projection_gate(
    result: IntentCompilationResult,
    *,
    run_id: str = "",
    context_version: str = "",
) -> GateDecision:
    stage = "target_projection"
    cv = context_version or result.context_version
    gate_artifact_id = "gate-target-projection-" + (result.artifact_id or "0")
    has_error_diagnostics = any(
        getattr(diagnostic, "severity", "warning") == "error"
        for diagnostic in (result.diagnostics or [])
    )
    has_admission_errors = any(
        getattr(diagnostic, "severity", "warning") == "error"
        and _is_admission_diagnostic(diagnostic)
        for diagnostic in (result.diagnostics or [])
    )

    if result.compilation_status == CompilationStatus.NEEDS_REVIEW:
        return GateDecision(
            stage=stage,
            passed=False,
            feedback_route="HUMAN",
            context_version=cv,
            artifact_id=gate_artifact_id,
            route_reason="target_projection_needs_review",
        )

    if has_admission_errors:
        return GateDecision(
            stage=stage,
            passed=False,
            feedback_route="HUMAN",
            context_version=cv,
            artifact_id=gate_artifact_id,
            route_reason="target_projection_admission_error",
        )

    if has_error_diagnostics:
        return GateDecision(
            stage=stage,
            passed=False,
            feedback_route="L3",
            context_version=cv,
            artifact_id=gate_artifact_id,
            route_reason="target_projection_semantic_error",
        )

    # Warning-only diagnostics remain non-blocking only when the compilation
    # status is not NEEDS_REVIEW.  The stage must explicitly leave the result
    # as DRAFT/VALIDATED when GROUND is allowed to resolve the warning.
    if _is_empty_intent(result):
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
