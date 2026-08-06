"""SELECT gate evaluator - 3-route decision over a SiteSelectionDecision.

Pure function: SiteSelectionDecision -> GateDecision. No I/O. Mirrors the gate
convention in app.agent.ground.gate with stage="select".

Routes (precedence high -> low):
  RETRY_GROUND -> not all targets got a parcel (selected_combination shorter
                  than target_count), so re-run ground for more candidates
  HUMAN   -> all targets placed but top-ranked score below
             ``confidence_threshold`` (needs human review)
  PASS    -> all targets placed and confidence acceptable

Determinism: routing is a pure function of the decision fields, no RNG, no LLM.
"""
from __future__ import annotations

from app.modules.schema.contracts.selection_contracts import SiteSelectionDecision
from app.modules.schema.contracts.workflow_contracts import GateDecision, PendingRequest

STAGE = "select"


def _top_score(decision: SiteSelectionDecision) -> float | None:
    best_by_target = decision.decision_factors.get("best_score_by_target", {}) or {}
    if best_by_target:
        return max(best_by_target.values())
    if decision.full_ranking:
        return max(c.score for c in decision.full_ranking)
    return None


def select_gate_route(
    decision: SiteSelectionDecision,
    *,
    target_count: int,
    confidence_threshold: float = 0.4,
) -> str:
    """Return the deterministic route: "PASS"|"RETRY_GROUND"|"HUMAN"."""
    if target_count > 0 and len(decision.selected_combination) < target_count:
        return "RETRY_GROUND"
    unplaced = decision.decision_factors.get("unplaced_count", 0) or 0
    if unplaced > 0:
        return "RETRY_GROUND"
    top = _top_score(decision)
    if top is not None and top < confidence_threshold:
        return "HUMAN"
    return "PASS"


def evaluate_select_gate(
    decision: SiteSelectionDecision,
    *,
    target_count: int,
    confidence_threshold: float = 0.4,
) -> GateDecision:
    stage = STAGE
    gate_artifact_id = "gate-select-" + (decision.artifact_id or "0")

    route = select_gate_route(
        decision, target_count=target_count, confidence_threshold=confidence_threshold
    )

    if route == "RETRY_GROUND":
        pending = [
            PendingRequest(
                request_id="pr-select-no-candidate-0",
                stage=stage,
                request_type="selection_no_candidate",
                context={
                    "reason": "selection_no_candidate",
                    "target_count": target_count,
                    "placed_count": len(decision.selected_combination),
                },
            )
        ]
        return GateDecision(
            stage=stage,
            passed=False,
            feedback_route="RETRY_GROUND",
            pending_requests=pending,
            context_version=decision.context_version,
            artifact_id=gate_artifact_id,
        )

    if route == "HUMAN":
        pending = [
            PendingRequest(
                request_id="pr-select-low-confidence-0",
                stage=stage,
                request_type="selection_low_confidence",
                context={
                    "reason": "selection_low_confidence",
                    "target_count": target_count,
                    "placed_count": len(decision.selected_combination),
                    "confidence": _top_score(decision),
                },
            )
        ]
        return GateDecision(
            stage=stage,
            passed=False,
            feedback_route="HUMAN",
            pending_requests=pending,
            context_version=decision.context_version,
            artifact_id=gate_artifact_id,
        )

    return GateDecision(
        stage=stage,
        passed=True,
        feedback_route=None,
        context_version=decision.context_version,
        artifact_id=gate_artifact_id,
    )


__all__ = ["evaluate_select_gate", "select_gate_route"]
