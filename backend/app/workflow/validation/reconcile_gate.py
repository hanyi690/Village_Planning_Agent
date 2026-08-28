"""RECONCILE gate - 4-way responsibility router over a FinalManifest.

Mirrors the VALIDATE gate convention (app.workflow.validation.validate_gate) with
stage="reconcile". Pure function: FinalManifest -> GateDecision.
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

from typing import Any

from app.core.common.gate_progress import gate_progress_metadata
from app.contracts.delivery.reconciliation_contracts import (
    ReconciliationInconsistency,
    FinalManifest,
)
from app.contracts.workflow.workflow_contracts import (
    GateDecision,
    PendingRequest,
    StageId,
)

STAGE = StageId.RECONCILE.value

_STAGE_ROUTE = {
    "L3": "RETRY_L3",
    "EXECUTE": "RETRY_EXECUTE",
}


def _error_counts(report: FinalManifest) -> dict[str, int]:
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


def reconcile_gate_route(report: FinalManifest) -> str:
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


def evaluate_reconcile_gate(
    report: FinalManifest,
    *,
    input_artifact_refs: dict[str, Any] | None = None,
    previous_gate: Any = None,
) -> GateDecision:
    stage = STAGE
    gate_artifact_id = "gate-reconcile-" + (report.artifact_id or "0")

    route = reconcile_gate_route(report)
    issue_payload = [item.model_dump(mode="json") for item in report.inconsistencies]
    progress, identical = gate_progress_metadata(
        input_artifact_refs=input_artifact_refs,
        output={
            "coverage_matrix": report.coverage_matrix.model_dump(mode="json"),
            "inconsistencies": issue_payload,
        },
        issues=issue_payload,
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
        stable_targets = {
            row.target_id for row in report.coverage_matrix.rows if row.target_id
        }
        target_ids = sorted({
            item.intervention_id
            for item in report.inconsistencies
            if item.severity == "error" and item.intervention_id in stable_targets
        })
        non_target_blocker_count = sum(
            1
            for item in report.inconsistencies
            if item.severity == "error" and item.intervention_id not in stable_targets
        )
        pending = [
            PendingRequest(
                request_id="pr-reconcile-" + route.lower() + "-0",
                stage=stage,
                request_type="reconcile_" + route.lower(),
                context={
                    "reason": route,
                    "stage": dominant,
                    "error_count": error_count,
                    "target_ids": target_ids,
                    "non_target_blocker_count": non_target_blocker_count,
                    "issue_fingerprint": progress["issue_fingerprint"],
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


__all__ = ["evaluate_reconcile_gate", "reconcile_gate_route"]
