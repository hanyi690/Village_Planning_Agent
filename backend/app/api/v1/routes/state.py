"""GET /sessions/{session_id}/state transport."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.api.v1.contracts import SessionProjection
from app.application.projections.session import ProjectionNotFoundError, session_projections
from app.application.queries.workflow_state import load_workflow_state


router = APIRouter(prefix="/api/v1", tags=["Stable v1"])


@router.get("/sessions/{session_id}/state", response_model=SessionProjection)
async def get_state(session_id: str) -> SessionProjection:
    state = await load_workflow_state(session_id)
    try:
        view = await session_projections.get(session_id, state=state)
    except ProjectionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return SessionProjection.model_validate(view.model_dump(mode="python"))


__all__ = ["get_state", "router"]
