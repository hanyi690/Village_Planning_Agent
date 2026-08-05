"""VALIDATE gate evaluator - 5-way responsibility router over a ValidationReport.

Pure function: ValidationReport -> GateDecision. No I/O, no LLM, no KG --
deterministic only. Mirrors the gate convention in app.agent.select.gate
with stage="validate".

Routes (precedence high -> low):
  PASS             -> all checks passed (overall_passed True)
  RETRY_EXECUTE    -> dominant error stage is EXECUTE
  RETRY_SELECT     -> dominant error stage is SELECT
  RETRY_GROUND     -> dominant error stage is GROUND
  RETRY_L3         -> dominant error stage is L3
  RETRY_PARSE      -> dominant error stage is PARSE
  HUMAN            -> tie between two+ dominant error stages, or only
                      warning-severity issues (no error issues)

Precedence: PASS wins immediately; then the stage with the most
error-severity issues (counted from report.issues_by_stage) maps to its
retry route; a tie or warnings-only falls back to HUMAN.

Determinism: routing is a pure function of the report fields, no RNG, no LLM.
Only RETRY_EXECUTE is wired in the current graph; Wave M connects the others.
"""
from __future__ import annotations

from app.modules.schema.contracts.validation_report_contracts import ValidationReport
from app.modules.schema.contracts.workflow_contracts import (
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
    "PARSE": "RETRY_PARSE",
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
    "PASS"|"RETRY_EXECUTE"|"RETRY_SELECT"|"RETRY_GROUND"|"RETRY_L3"|"RETRY_PARSE"|"HUMAN".
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


def evaluate_validate_gate(report: ValidationReport) -> GateDecision:
    stage = STAGE
    gate_artifact_id = "gate-validate-" + (report.artifact_id or "0")

    route = validate_gate_route(report)

    if route != "PASS":
        counts = _error_counts(report)
        dominant, error_count = _dominant_stage(counts)
        pending = [
            PendingRequest(
                request_id="pr-validate-" + route.lower() + "-0",
                stage=stage,
                request_type="validation_" + route.lower(),
                context={
                    "reason": route,
                    "stage": dominant,
                    "error_issue_count": error_count,
                },
            )
        ]
        return GateDecision(
            stage=stage,
            passed=False,
            feedback_route=route,
            pending_requests=pending,
            context_version=report.context_version,
            artifact_id=gate_artifact_id,
        )

    return GateDecision(
        stage=stage,
        passed=True,
        feedback_route=None,
        pending_requests=[],
        context_version=report.context_version,
        artifact_id=gate_artifact_id,
    )


__all__ = ["evaluate_validate_gate", "validate_gate_route"]
