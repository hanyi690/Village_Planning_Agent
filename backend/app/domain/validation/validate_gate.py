"""VALIDATE gate evaluator - 5-way responsibility router over a ValidationReport.

Pure function: ValidationReport -> GateDecision. No I/O, no LLM, no KG --
deterministic only. Mirrors the gate convention in app.domain.allocation.select_gate
with stage="validate".

Routes (precedence high -> low):
  PASS             -> all checks passed (overall_passed True)
  RETRY_EXECUTE    -> dominant error stage is EXECUTE
  RETRY_SELECT     -> dominant error stage is SELECT
  RETRY_GROUND     -> dominant error stage is GROUND
  RETRY_L3         -> dominant error stage is L3
  RETRY_TARGET_PROJECTION -> dominant error stage is target projection
  HUMAN            -> tie between two+ dominant error stages, or only
                      warning-severity issues (no error issues)

Precedence: PASS wins immediately; then the stage with the most
error-severity issues (counted from report.issues_by_stage) maps to its
retry route; a tie or warnings-only falls back to HUMAN.

Determinism: routing is a pure function of the report fields, no RNG, no LLM.
Only RETRY_EXECUTE is wired in the current graph; Wave M connects the others.
"""
from __future__ import annotations

from typing import Any

from app.domain.common.gate_progress import gate_progress_metadata
from app.contracts.artifacts.validation_report_contracts import ValidationReport
from app.contracts.workflow.workflow_contracts import (
    GateDecision,
    PendingRequest,
    StageId,
)

STAGE = StageId.VALIDATE.value

_STAGE_ROUTE = {
    "EXECUTE": "RETRY_EXECUTE",
    "SELECT": "RETRY_SELECT",
    "GROUND": "RETRY_GROUND",
    "L3": "RETRY_L3",
    "TARGET_PROJECTION": "RETRY_TARGET_PROJECTION",
}


def _error_counts(report: ValidationReport) -> dict[str, int]:
    """Count error-severity ValidationIssues per stage (skips empty stages)."""
    counts: dict[str, int] = {}
    for stage, issues in (report.issues_by_stage or {}).items():
        n = sum(1 for i in issues if i.severity == "error")
        if n > 0:
            counts[stage] = n
    return counts


def _dominant_stage(counts: dict[str, int]) -> tuple[str | None, int]:
    """Return (stage, count) of the unique max, or (None, max) on a tie."""
    if not counts:
        return None, 0
    max_count = max(counts.values())
    leaders = [s for s, n in counts.items() if n == max_count]
    if len(leaders) == 1:
        return leaders[0], max_count
    return None, max_count


def validate_gate_route(report: ValidationReport) -> str:
    """Return the deterministic route:
    "PASS"|"RETRY_EXECUTE"|"RETRY_SELECT"|"RETRY_GROUND"|"RETRY_L3"|"RETRY_TARGET_PROJECTION"|"HUMAN".
    """
    if report.overall_passed:
        return "PASS"
    counts = _error_counts(report)
    if not counts:
        return "HUMAN"
    stage, _ = _dominant_stage(counts)
    if stage is None:
        return "HUMAN"
    return _STAGE_ROUTE[stage]


def evaluate_validate_gate(
    report: ValidationReport,
    *,
    input_artifact_refs: dict[str, Any] | None = None,
    previous_gate: Any = None,
) -> GateDecision:
    stage = STAGE
    gate_artifact_id = "gate-validate-" + (report.artifact_id or "0")

    route = validate_gate_route(report)
    failed_checks = [
        check.model_dump(mode="json")
        for check in report.checks
        if not check.passed
    ]
    progress, identical = gate_progress_metadata(
        input_artifact_refs=input_artifact_refs,
        output={"checks": failed_checks, "overall_passed": report.overall_passed},
        issues=report.issues_by_stage,
        previous_gate=previous_gate,
    )
    route_reason = "checks_passed" if route == "PASS" else f"dominant_route:{route}"
    if route.startswith("RETRY_") and identical:
        route = "HUMAN"
        route_reason = "identical_no_progress"
    elif route.startswith("RETRY_") and progress["inputs_changed"] is False:
        route = "HUMAN"
        route_reason = "inputs_unchanged"

    if route != "PASS":
        counts = _error_counts(report)
        dominant, error_count = _dominant_stage(counts)
        target_ids = sorted({
            target_id
            for check in report.checks
            if not check.passed
            for target_id in check.affected_target_ids
            if target_id
        })
        non_target_blocker_count = sum(
            1
            for check in report.checks
            if not check.passed and not check.affected_target_ids
        )
        affected_parcels = sorted({
            parcel
            for check in report.checks
            if not check.passed
            for parcel in check.affected_parcels
            if parcel
        })
        evidence_refs = sorted({
            ref
            for check in report.checks
            if not check.passed
            for ref in check.evidence_refs
            if ref
        })
        pending = [
            PendingRequest(
                request_id="pr-validate-" + route.lower() + "-0",
                stage=stage,
                request_type="validation_" + route.lower(),
                context={
                    "reason": route,
                    "stage": dominant,
                    "error_issue_count": error_count,
                    "target_ids": target_ids,
                    "affected_parcels": affected_parcels,
                    "evidence_refs": evidence_refs,
                    "non_target_blocker_count": non_target_blocker_count,
                    "issue_fingerprint": progress["issue_fingerprint"],
                    # Preserve the complete typed failure payload at the
                    # iteration boundary. The artifact remains authoritative;
                    # this bounded copy lets HUMAN/LLM callers act without
                    # guessing which target, parcel, or evidence caused the
                    # route.
                    "failed_checks": failed_checks,
                },
            )
        ]
        return GateDecision(
            stage=stage,
            passed=False,
            feedback_route=route,
            pending_requests=pending,
            evidence_requests=evidence_refs,
            context_version=report.context_version,
            artifact_id=gate_artifact_id,
            route_reason=route_reason,
            **progress,
        )

    return GateDecision(
        stage=stage,
        passed=True,
        feedback_route=None,
        pending_requests=[],
        context_version=report.context_version,
        artifact_id=gate_artifact_id,
        route_reason=route_reason,
        **progress,
    )


__all__ = ["evaluate_validate_gate", "validate_gate_route"]
