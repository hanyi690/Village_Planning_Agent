"""Application-side HUMAN review projection from checkpoint gate channels."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from app.workflow.stages.support import GATE_CHANNELS


def _collect_gate_items(state: Dict[str, Any]) -> Tuple[Optional[str], List[Dict[str, Any]]]:
    """Collect pending requests from the downstream-most HUMAN gate."""

    for gate_attr in GATE_CHANNELS:
        gate = state.get(gate_attr)
        if gate is None:
            continue
        route = getattr(gate, "feedback_route", None)
        if route is None and isinstance(gate, dict):
            route = gate.get("feedback_route")
        if route != "HUMAN":
            continue
        pending = getattr(gate, "pending_requests", None)
        if pending is None and isinstance(gate, dict):
            pending = gate.get("pending_requests")
        items: List[Dict[str, Any]] = []
        for item in pending or []:
            if hasattr(item, "model_dump"):
                items.append(item.model_dump())
            elif isinstance(item, dict):
                items.append(item)
        return gate_attr.replace("_gate", ""), items
    return None, []


def _retry_exhaustion_items(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Create a compact diagnostic review item when no gate has pending items."""

    validation_feedback = state.get("validation_feedback") or {}
    if not state.get("error_feedback") and not validation_feedback:
        return []
    context = {
        "message": "post-L3 retries exhausted; manual intervention required",
        "detail": dict(state.get("error_feedback") or {}),
        "retry_counts": dict(state.get("retry") or state.get("retry_counts") or {}),
        "max_retries": state.get("max_retries", 3),
    }
    if isinstance(validation_feedback, dict) and validation_feedback:
        context.update({
            "validation_status": validation_feedback.get("status", ""),
            "failed_checks": list(validation_feedback.get("failed_checks") or []),
            "affected_target_ids": list(
                validation_feedback.get("affected_target_ids") or []
            ),
            "affected_parcels": list(
                validation_feedback.get("affected_parcels") or []
            ),
            "evidence_refs": list(validation_feedback.get("evidence_refs") or []),
            "next_action": dict(validation_feedback.get("next_action") or {}),
            "repair_impact": dict(validation_feedback.get("repair_impact") or {}),
        })
    return [{
        "request_id": "post-l3-retry-exhausted",
        "stage": "post_l3",
        "request_type": "retry_exhausted",
        "context": context,
    }]


def _retry_exhaustion_stage(state: Dict[str, Any]) -> str:
    counts = state.get("retry") or state.get("retry_counts") or {}
    max_retries = state.get("max_retries", 3)
    for stage, count in counts.items():
        if count >= max_retries:
            return str(stage)
    return "post_l3"


def collect_human_review_items(state: Dict[str, Any]) -> Tuple[Optional[str], List[Dict[str, Any]]]:
    """Return the current application HUMAN projection."""

    stage, items = _collect_gate_items(state)
    if stage is not None:
        return stage, items
    return _retry_exhaustion_stage(state), _retry_exhaustion_items(state)


__all__ = ["collect_human_review_items"]
