"""Planning target projection gate.

Pure function: IntentCompilationResult -> GateDecision. No I/O.

Routes:
  PASS   -> projection validated with non-empty intent or explicit pending work
  L3     -> non-admission semantic error requiring compiler rework
  HUMAN  -> unresolved admission, needs-review, or empty intent
"""
from __future__ import annotations

from typing import Any

from app.contracts.target_projection.parse_result_contracts import (
    CompilationStatus,
    IntentCompilationResult,
)
from app.contracts.workflow.workflow_contracts import GateDecision


def validate_target_projection_boundary(result: IntentCompilationResult) -> None:
    """Reject concrete binding/materialization state before TARGET persistence."""

    forbidden = {
        "entity_ref",
        "existing_entity_ref",
        "start_entity_ref",
        "end_entity_ref",
        "representation_ref",
        "resource_ref",
        "geometry_ref",
        "geometry",
        "geometry_wkt",
        "anchor",
        "anchors",
        "candidate_id",
        "candidate_ids",
        "candidate_bsms",
        "candidate_refs",
        "bsm",
        "bsms",
        "scenario",
        "scenario_id",
        "approval",
        "approval_id",
    }

    def present(value: Any) -> bool:
        return value not in (None, "", [], {}, ())

    def visit(value: Any, path: str = "target_projection") -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if str(key).casefold() in forbidden and present(child):
                    raise RuntimeError(
                        f"TARGET_PROJECTION contains forbidden binding {path}.{key}"
                    )
                visit(child, f"{path}.{key}")
        elif isinstance(value, list):
            for index, child in enumerate(value):
                visit(child, f"{path}[{index}]")

    visit(result.model_dump(mode="json"))
    row_refs = {item.target_ref for item in result.target_projection_rows}
    for row in result.target_projection_rows:
        if row.route_to != "ground":
            raise RuntimeError("TARGET_PROJECTION may only route targets to GROUND")
    bypass_by_ref = {item.bypass_ref: item for item in result.bypass_records}
    for row in result.target_projection_rows:
        if not row.bypass_ref:
            continue
        bypass = bypass_by_ref.get(row.bypass_ref)
        if bypass is None or bypass.target_ref != row.target_ref:
            raise RuntimeError("TARGET_PROJECTION bypass lineage is incomplete")
    if any(item.target_ref not in row_refs for item in result.bypass_records):
        raise RuntimeError("TARGET_PROJECTION bypass refers to an unknown target")


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


def _has_pending_grounding_work(result: IntentCompilationResult) -> bool:
    """Return whether the projection produced concrete non-executable work."""

    return bool(
        result.pending_grounding_claims
        or result.pending_grounding_specs
        or result.pending_grounding_requests
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
    if _is_empty_intent(result) and not _has_pending_grounding_work(result):
        return GateDecision(
            stage=stage,
            passed=False,
            feedback_route="HUMAN",
            context_version=cv,
            artifact_id=gate_artifact_id,
        )

    if _is_empty_intent(result):
        return GateDecision(
            stage=stage,
            passed=True,
            feedback_route=None,
            context_version=cv,
            artifact_id=gate_artifact_id,
            route_reason="passed_with_pending_grounding",
        )

    return GateDecision(
        stage=stage,
        passed=True,
        feedback_route=None,
        context_version=cv,
        artifact_id=gate_artifact_id,
    )


__all__ = ["evaluate_target_projection_gate", "validate_target_projection_boundary"]
