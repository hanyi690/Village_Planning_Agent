"""Canonical HUMAN interrupt contracts.

Both step-mode layer review and post-L3 review use the same LangGraph
interrupt protocol.  Legacy field names are accepted at the boundary, but
new graph state, SSE events, and UI projections should use this contract.
"""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Any, Dict, Iterable, Optional

from pydantic import BaseModel, ConfigDict, Field


class HumanInterruptChannel(StrEnum):
    """The graph branch that owns the pause."""

    STEP_MODE = "step_mode"
    POST_L3_REVIEW = "post_l3_review"


class HumanInterruptReason(StrEnum):
    """Stable reason understood by every client."""

    HUMAN_REVIEW_REQUIRED = "human_review_required"


class HumanInterruptItem(BaseModel):
    """One actionable review request.

    ``context`` intentionally remains open-ended because each post-L3 gate
    can provide different evidence without changing the transport contract.
    """

    model_config = ConfigDict(extra="allow")

    request_id: str
    stage: str
    request_type: str
    context: Dict[str, Any] = Field(default_factory=dict)


class HumanInterrupt(BaseModel):
    """Payload passed to ``interrupt()`` and exposed to the UI."""

    model_config = ConfigDict(extra="allow")

    event_id: str
    channel: HumanInterruptChannel
    reason: HumanInterruptReason = HumanInterruptReason.HUMAN_REVIEW_REQUIRED
    layer: Optional[int] = None
    phase: Optional[str] = None
    layer_name: Optional[str] = None
    paused_stage: Optional[str] = None
    items: list[HumanInterruptItem] = Field(default_factory=list)
    error_feedback: Dict[str, str] = Field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        """Return a JSON-compatible payload for LangGraph/SSE/state."""

        return self.model_dump(mode="json")


def stable_human_interrupt_id(
    session_id: str,
    channel: HumanInterruptChannel,
    *,
    layer: Optional[int] = None,
    phase: Optional[str] = None,
    paused_stage: Optional[str] = None,
    items: Iterable[Dict[str, Any]] = (),
    retry_counts: Optional[Dict[str, int]] = None,
) -> str:
    """Create a deterministic idempotency key for one HUMAN checkpoint."""

    material = {
        "session_id": session_id,
        "channel": channel.value,
        "layer": layer,
        "phase": phase,
        "paused_stage": paused_stage,
        "items": list(items),
        "retry_counts": retry_counts or {},
    }
    encoded = json.dumps(
        material,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:24]


def build_human_interrupt(
    *,
    event_id: str,
    channel: HumanInterruptChannel,
    items: Iterable[Dict[str, Any]],
    layer: Optional[int] = None,
    phase: Optional[str] = None,
    layer_name: Optional[str] = None,
    paused_stage: Optional[str] = None,
    error_feedback: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Validate and serialize a canonical interrupt payload."""

    payload = HumanInterrupt(
        event_id=event_id,
        channel=channel,
        layer=layer,
        phase=phase,
        layer_name=layer_name,
        paused_stage=paused_stage,
        items=list(items),
        error_feedback=dict(error_feedback or {}),
    ).as_dict()
    # Keep transport-only aliases for older clients and persisted checkpoints.
    # New code must read ``items`` and ``event_id``.
    payload["human_review_items"] = payload["items"]
    payload["human_review_event_id"] = payload["event_id"]
    return payload


def normalize_human_interrupt(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize old interrupt payloads at an API/checkpoint boundary.

    This is the boundary that accepts the historical names
    ``human_review_items`` and ``human_review_event_id``.  The builder emits
    those names only as transport compatibility aliases; new callers should
    construct and consume the canonical fields.
    """

    raw_reason = str(payload.get("reason") or "")
    raw_channel = payload.get("channel")
    channel = (
        HumanInterruptChannel(str(raw_channel))
        if raw_channel in {item.value for item in HumanInterruptChannel}
        else (
            HumanInterruptChannel.STEP_MODE
            if raw_reason.startswith("step_mode") or payload.get("layer")
            else HumanInterruptChannel.POST_L3_REVIEW
        )
    )
    raw_items = payload.get("items")
    if raw_items is None:
        raw_items = payload.get("human_review_items") or []
    event_id = str(
        payload.get("event_id")
        or payload.get("human_review_event_id")
        or "unknown-human-interrupt"
    )
    normalized = build_human_interrupt(
        event_id=event_id,
        channel=channel,
        items=raw_items,
        layer=payload.get("layer"),
        phase=payload.get("phase"),
        layer_name=payload.get("layer_name"),
        paused_stage=payload.get("paused_stage"),
        error_feedback=payload.get("error_feedback"),
    )
    return normalized


def normalize_human_decision(payload: Any) -> Dict[str, Any]:
    """Normalize a resume value before graph business logic consumes it."""

    if not isinstance(payload, dict):
        return {"action": "approve"}
    decision = dict(payload)
    if decision.get("action") == "accept":
        decision["action"] = "approve"
    return decision


__all__ = [
    "HumanInterrupt",
    "HumanInterruptChannel",
    "HumanInterruptItem",
    "HumanInterruptReason",
    "build_human_interrupt",
    "normalize_human_decision",
    "normalize_human_interrupt",
    "stable_human_interrupt_id",
]
