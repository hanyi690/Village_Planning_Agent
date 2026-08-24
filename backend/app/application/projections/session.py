"""Session and HUMAN public projections."""

from __future__ import annotations

from app.application.projections.models import HumanReviewView, SessionView
from app.application.queries.artifacts import artifact_queries
from app.application.queries.run_events import run_event_queries
from app.application.queries.workflow_state import load_workflow_state
from app.database.operations import get_planning_session_async


class ProjectionNotFoundError(LookupError):
    """The requested session projection has no checkpoint."""


_STAGE_TRANSITION_TYPES = frozenset({
    "layer_started",
    "layer_completed",
    "dimension_start",
    "dimension_complete",
})


def _status(
    state: dict[str, object],
    persisted: dict[str, object] | None = None,
) -> str:
    if state.get("fatal_error") or str((persisted or {}).get("execution_error") or ""):
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


def _event_data(event: dict[str, object] | None) -> dict[str, object]:
    if not isinstance(event, dict):
        return {}
    data = event.get("data")
    return data if isinstance(data, dict) else event


def _event_layer(data: dict[str, object]) -> int | None:
    layer = data.get("layer")
    if isinstance(layer, bool):
        layer = None
    if isinstance(layer, (int, float)) and int(layer) in {1, 2, 3}:
        return int(layer)
    stage = str(data.get("stage") or "").strip().upper()
    if stage in {"L1", "L2", "L3"}:
        return int(stage[-1])
    return None


def _latest_stage_transition(
    events: list[dict[str, object]],
    fallback: dict[str, object] | None = None,
) -> dict[str, object] | None:
    """Ignore stale worker reports that arrive after a newer layer start.

    LangGraph can flush a trailing L1 ``step_report`` after the parent has
    already emitted ``layer_started(layer=2)``. A public ``/state`` projection
    must follow the ordered stage transition, not whichever worker report was
    inserted last. A later layer start begins a new monotonic segment; within
    that segment dimension transitions update the visible stage normally.
    """

    markers: list[tuple[int, int, dict[str, object]]] = []
    for event in events:
        data = _event_data(event)
        kind = str(data.get("type") or "").strip()
        if kind not in _STAGE_TRANSITION_TYPES:
            continue
        layer = _event_layer(data)
        if layer is None:
            continue
        try:
            seq = int(event.get("seq") or 0)
        except (TypeError, ValueError):
            seq = 0
        markers.append((seq, layer, event))
    if not markers:
        return fallback
    starts = [
        item for item in markers
        if _event_data(item[2]).get("type") == "layer_started"
    ]
    if starts:
        start_seq, start_layer, start_event = max(starts, key=lambda item: item[0])
        segment = [
            item for item in markers
            if item[0] >= start_seq and item[1] >= start_layer
        ]
        if segment:
            return max(segment, key=lambda item: item[0])[2]
        return start_event
    return max(markers, key=lambda item: item[0])[2]


def _project_live_phase(
    state: dict[str, object],
    latest_event: dict[str, object] | None,
) -> str:
    """Use the newest layer-bearing event when the checkpoint lags the log."""
    data = _event_data(latest_event)
    layer = data.get("layer")
    if isinstance(layer, bool):
        layer = None
    if isinstance(layer, (int, float)) and int(layer) in {1, 2, 3}:
        return f"layer{int(layer)}"
    stage = data.get("stage")
    if isinstance(stage, str) and stage.strip().upper() in {"L1", "L2", "L3"}:
        return f"layer{stage.strip()[-1]}"
    return str(state.get("phase") or "")


def _project_live_stage(
    state: dict[str, object],
    manifest_payload: dict[str, object],
    latest_event: dict[str, object] | None,
) -> str:
    if state.get("delivery_status") or manifest_payload.get("delivery_status"):
        return "deliver"
    data = _event_data(latest_event)
    stage = data.get("stage")
    if isinstance(stage, str) and stage.strip():
        return stage.strip()
    layer = data.get("layer")
    if isinstance(layer, bool):
        layer = None
    if isinstance(layer, (int, float)) and int(layer) in {1, 2, 3}:
        return f"L{int(layer)}"
    return str(state.get("active_stage") or "")


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
        persisted = await get_planning_session_async(session_id) or {}
        manifest = await artifact_queries.read(session_id, "delivery_manifest")
        manifest_payload = manifest.payload if manifest else {}
        if not isinstance(manifest_payload, dict):
            manifest_payload = {}
        recent_events = await run_event_queries.recent(session_id)
        latest_event = (
            recent_events[-1]
            if recent_events
            else await run_event_queries.latest(session_id)
        )
        live_stage_event = _latest_stage_transition(recent_events, latest_event)
        phase = _project_live_phase(control, live_stage_event)
        config = control.get("config")
        config = config if isinstance(config, dict) else {}
        return SessionView(
            session_id=session_id,
            project_name=str(
                config.get("project_name")
                or control.get("project_name")
                or persisted.get("project_name")
                or ""
            ),
            village_name=str(
                config.get("village_name")
                or control.get("village_name")
                or persisted.get("village_name")
                or ""
            ),
            status=_status(control, persisted),
            active_stage=_project_live_stage(control, manifest_payload, live_stage_event),
            phase=phase,
            progress=_progress({**control, "phase": phase}),
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
