"""Application query for the HUMAN review projection from checkpoint state."""

from __future__ import annotations

from typing import Protocol

from app.application.queries.workflow_state import load_workflow_state


class ReviewStorePort(Protocol):
    """Reads the stable workflow control state owned by the checkpoint."""

    async def load(self, session_id: str) -> dict[str, object] | None: ...


class _ReviewStore:
    async def load(self, session_id: str) -> dict[str, object] | None:
        return await load_workflow_state(session_id)


async def get_human_review(
    session_id: str,
    *,
    review_store: ReviewStorePort,
) -> dict[str, object]:
    """Return the active HUMAN review projection as a serializable dict."""

    control = await review_store.load(session_id)
    if not control:
        return {
            "session_id": session_id,
            "pending": False,
            "event_id": None,
            "paused_stage": "",
            "items": [],
        }
    interrupt = dict(control.get("interrupt_ref") or {})
    items = [item for item in interrupt.get("items") or [] if isinstance(item, dict)]
    return {
        "session_id": session_id,
        "pending": bool(items or interrupt),
        "event_id": (
            str(interrupt.get("event_id")) if interrupt.get("event_id") else None
        ),
        "paused_stage": str(
            interrupt.get("paused_stage") or control.get("active_stage") or ""
        ),
        "items": items,
    }


__all__ = ["ReviewStorePort", "get_human_review"]
