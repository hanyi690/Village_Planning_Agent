"""RECONCILE gate - 4-way responsibility router over a ReconciliationReport.

Mirrors the VALIDATE gate convention (app.agent.validate.gate) with
stage="reconcile". Pure function: ReconciliationReport -> GateDecision.
No I/O, no LLM, no KG - deterministic only.

Routes (precedence high -> low):
  PASS            -> no inconsistencies, or only warning-severity ones
  RETRY_L3        -> dominant error stage is L3 (unique max)
  RETRY_EXECUTE   -> dominant error stage is EXECUTE (unique max)
  HUMAN           -> tie between two+ dominant error stages, or the dominant
                     error stage has no auto-retry target (PARSE/GROUND/
                     SELECT pre-Wave-M)

Precedence: PASS wins immediately; then the stage with the most error-
severity inconsistencies maps to its retry route; a tie or a non-retryable
dominant stage falls back to HUMAN.

Determinism: routing is a pure function of the report fields, no RNG, no LLM.
Only the gate function is delivered here; main graph wiring lands in Wave M.
"""
from __future__ import annotations

from app.modules.schema.contracts.reconciliation_contracts import (
    ReconciliationInconsistency,
    ReconciliationReport,
)
from app.modules.schema.contracts.workflow_contracts import (
    GateDecision,
    PendingRequest,
    StageId,
)

STAGE = StageId.RECONCILE.value

_STAGE_ROUTE = {
    "L3": "RETRY_L3",
    "EXECUTE": "RETRY_EXECUTE",
}


def _error_counts(report: ReconciliationReport) -> dict[str, int]:
    """Count error-severity inconsistencies per responsible_stage (skips empty)."""
    counts: dict[str, int] = {}
    for inc in report.inconsistencies or []:
        if inc.severity == "error":
            counts[inc.responsible_stage] = counts.get(inc.responsible_stage, 0) + 1
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


def reconcile_gate_route(report: ReconciliationReport) -> str:
    """Return the deterministic route:
    "PASS"|"RETRY_L3"|"RETRY_EXECUTE"|"HUMAN".
    """
    if not report.inconsistencies:
        return "PASS"
    if all(inc.severity != "error" for inc in report.inconsistencies):
        return "PASS"
    counts = _error_counts(report)
    if not counts:
        return "HUMAN"
    stage, _ = _dominant_stage(counts)
    if stage is None:
        return "HUMAN"
    return _STAGE_ROUTE.get(stage, "HUMAN")


def evaluate_reconcile_gate(report: ReconciliationReport) -> GateDecision:
    stage = STAGE
    gate_artifact_id = "gate-reconcile-" + (report.artifact_id or "0")

    route = reconcile_gate_route(report)

    if route != "PASS":
        counts = _error_counts(report)
        dominant, error_count = _dominant_stage(counts)
        pending = [
            PendingRequest(
                request_id="pr-reconcile-" + route.lower() + "-0",
                stage=stage,
                request_type="reconcile_" + route.lower(),
                context={
                    "reason": route,
                    "stage": dominant,
                    "error_count": error_count,
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


__all__ = ["evaluate_reconcile_gate", "reconcile_gate_route"]
