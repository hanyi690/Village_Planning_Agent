"""Public event projection shared by sync REST and SSE transport."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4


def public_event(session_id: str, event: dict[str, object]) -> dict[str, object]:
    seq = int(event.get("seq") or 0)
    event_type = str(event.get("type") or "progress")
    public_type = "progress"
    data: object = dict(event)
    if event_type == "human_review_paused":
        public_type = "human_review"
        data = {
            "schema_version": "1.0",
            "session_id": session_id,
            "pending": True,
            "event_id": str(event.get("event_id") or "") or None,
            "paused_stage": str(event.get("paused_stage") or ""),
            "items": list(event.get("items") or []),
        }
    elif event_type == "completed":
        public_type = "completed"
        data = {"delivery_status": event.get("delivery_status")}
    elif event_type == "error":
        public_type = "failed"
        data = {
            "schema_version": "1.0",
            "code": str(event.get("code") or "EXECUTION_FAILED"),
            "message": str(event.get("message") or event.get("error") or "execution failed"),
            "request_id": str(event.get("request_id") or uuid4()),
            "retryable": bool(event.get("retryable", False)),
            "details": {},
        }
    occurred_at = event.get("timestamp")
    if isinstance(occurred_at, str):
        try:
            occurred_at = datetime.fromisoformat(occurred_at.replace("Z", "+00:00"))
        except ValueError:
            occurred_at = None
    if not isinstance(occurred_at, datetime):
        occurred_at = datetime.now(timezone.utc)
    return {
        "schema_version": "1.0",
        "event_id": f"{session_id}:{seq}",
        "seq": seq,
        "session_id": session_id,
        "occurred_at": occurred_at,
        "type": public_type,
        "data": data,
    }


__all__ = ["public_event"]
