"""SELECT gate evaluator - 3-route decision over a SiteSelectionDecision.

Pure function: SiteSelectionDecision -> GateDecision. No I/O. Mirrors the gate
convention in app.domain.ground.gate with stage="select".

Routes (precedence high -> low):
  HUMAN   -> one or more target assignments is unplaced; the target must be
             explicitly deferred or reviewed rather than repeating GROUND
  HUMAN   -> all targets placed but top-ranked score below
             ``confidence_threshold`` (needs human review)
  PASS    -> all targets placed and confidence acceptable

Determinism: routing is a pure function of the decision fields, no RNG, no LLM.
"""
from __future__ import annotations

from typing import Any

from app.modules.schema.contracts.selection_contracts import SiteSelectionDecision
from app.modules.schema.contracts.workflow_contracts import GateDecision, PendingRequest
from app.domain.common.gate_progress import gate_progress_metadata

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
    portfolio_decision: Any = None,
) -> str:
    """Return the deterministic route: "PASS"|"HUMAN"."""
    if portfolio_decision is not None and str(
        getattr(portfolio_decision, "solver_status", "")
    ) not in {"OPTIMAL", "FEASIBLE"}:
        return "HUMAN"
    unplaced = decision.decision_factors.get("unplaced_count", 0) or 0
    if unplaced > 0:
        return "HUMAN"
    top = _top_score(decision)
    if top is not None and top < confidence_threshold:
        return "HUMAN"
    return "PASS"


def evaluate_select_gate(
    decision: SiteSelectionDecision,
    *,
    target_count: int,
    confidence_threshold: float = 0.4,
    input_artifact_refs: dict | None = None,
    previous_gate: Any = None,
    portfolio_decision: Any = None,
) -> GateDecision:
    stage = STAGE
    gate_artifact_id = "gate-select-" + (decision.artifact_id or "0")

    route = select_gate_route(
        decision,
        target_count=target_count,
        confidence_threshold=confidence_threshold,
        portfolio_decision=portfolio_decision,
    )

    unplaced_target_ids = [
        assignment.target_id
        for assignment in (decision.target_assignments or [])
        if assignment.status == "unplaced" and assignment.target_id
    ]
    portfolio_unmet_target_ids = [
        str(item).removeprefix("demand:")
        for item in (getattr(portfolio_decision, "unmet_demand", ()) or [])
        if str(item)
    ]
    review_target_ids = sorted(set(unplaced_target_ids + portfolio_unmet_target_ids))
    progress, identical = gate_progress_metadata(
        input_artifact_refs=input_artifact_refs,
        output={
            "unplaced_count": decision.decision_factors.get("unplaced_count", 0) or 0,
            "selected_combination": decision.selected_combination,
            "best_score_by_target": decision.decision_factors.get("best_score_by_target", {}),
            "portfolio_solver_status": getattr(portfolio_decision, "solver_status", ""),
            "portfolio_unmet_demand": list(getattr(portfolio_decision, "unmet_demand", ()) or []),
        },
        issues=review_target_ids,
        previous_gate=previous_gate,
    )
    route_reason = "all_placed" if route == "PASS" else "unplaced_or_low_confidence"
    if route == "HUMAN" and portfolio_decision is not None and str(
        getattr(portfolio_decision, "solver_status", "")
    ) not in {"OPTIMAL", "FEASIBLE"}:
        route_reason = "portfolio_infeasible"
    if route == "HUMAN" and progress["inputs_changed"] is False:
        route_reason = "inputs_unchanged"

    if route == "HUMAN" and review_target_ids:
        pending = [
            PendingRequest(
                request_id="pr-select-unplaced-targets",
                stage=stage,
                request_type="selection_no_candidate",
                context={
                    "reason": "portfolio_infeasible" if route_reason == "portfolio_infeasible" else "selection_no_candidate",
                    "target_ids": review_target_ids,
                    "target_count": target_count,
                    "placed_count": len(decision.selected_combination),
                    "issue_fingerprint": progress["issue_fingerprint"],
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
            route_reason=route_reason,
            **progress,
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
                    "issue_fingerprint": progress["issue_fingerprint"],
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
            route_reason=route_reason,
            **progress,
        )

    return GateDecision(
        stage=stage,
        passed=True,
        feedback_route=None,
        context_version=decision.context_version,
        artifact_id=gate_artifact_id,
        route_reason="all_placed",
        **progress,
    )


__all__ = ["evaluate_select_gate", "select_gate_route"]
