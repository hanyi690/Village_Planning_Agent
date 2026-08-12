"""Session and HUMAN public projections."""

from __future__ import annotations

from app.application.projections.models import HumanReviewView, SessionView
from app.application.queries.artifacts import artifact_queries
from app.application.queries.run_events import run_event_queries
from app.application.queries.workflow_state import load_workflow_state


class ProjectionNotFoundError(LookupError):
    """The requested session projection has no checkpoint."""


def _status(state: dict[str, object]) -> str:
    if state.get("fatal_error"):
        return "failed"
    if state.get("interrupt_ref") or state.get("paused_stage"):
        return "paused"
    if state.get("delivery_status"):
        return "completed"
    value = str(state.get("status") or "running")
    return value if value in {
        "pending", "running", "paused", "reviewing", "revising", "completed", "failed",
    } else "running"


def _progress(state: dict[str, object]) -> float:
    if state.get("delivery_status"):
        return 100.0
    phase = str(state.get("phase") or "")
    return {"layer1": 15.0, "layer2": 35.0, "layer3": 55.0}.get(phase, 70.0 if phase else 0.0)


def _links(session_id: str) -> dict[str, str]:
    base = f"/api/v1/sessions/{session_id}"
    return {
        "events": f"{base}/events",
        "event_sync": f"{base}/events/sync",
        "delivery": f"{base}/delivery",
        "map_layers": f"{base}/map-layers",
        "human_review": f"{base}/human-review",
        "resume": f"{base}/resume",
    }


class SessionProjectionService:
    async def get(
        self,
        session_id: str,
        *,
        state: dict[str, object] | None = None,
    ) -> SessionView:
        control = state or await load_workflow_state(session_id)
        if not control:
            raise ProjectionNotFoundError("session not found")
        manifest = await artifact_queries.read(session_id, "delivery_manifest")
        manifest_payload = manifest.payload if manifest else {}
        if not isinstance(manifest_payload, dict):
            manifest_payload = {}
        return SessionView(
            session_id=session_id,
            status=_status(control),
            active_stage=str(control.get("active_stage") or ""),
            phase=str(control.get("phase") or ""),
            progress=_progress(control),
            human_review_pending=bool(control.get("interrupt_ref")),
            delivery_status=(
                str(control.get("delivery_status"))
                if control.get("delivery_status")
                else str(manifest_payload.get("delivery_status"))
                if manifest_payload.get("delivery_status")
                else None
            ),
            statutory_complete=bool(manifest_payload.get("statutory_complete")),
            last_event_seq=await run_event_queries.last_seq(session_id),
            links=_links(session_id),
        )

    async def human_review(self, session_id: str) -> HumanReviewView:
        control = await load_workflow_state(session_id)
        if not control:
            raise ProjectionNotFoundError("session not found")
        interrupt = dict(control.get("interrupt_ref") or {})
        items = [item for item in interrupt.get("items") or [] if isinstance(item, dict)]
        return HumanReviewView(
            session_id=session_id,
            pending=bool(items or interrupt),
            event_id=str(interrupt.get("event_id")) if interrupt.get("event_id") else None,
            paused_stage=str(interrupt.get("paused_stage") or control.get("active_stage") or ""),
            items=items,
        )


session_projections = SessionProjectionService()


__all__ = ["ProjectionNotFoundError", "SessionProjectionService", "session_projections"]
