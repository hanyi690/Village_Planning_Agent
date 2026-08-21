"""Read-only process trace projection for the spatial planning chain."""

from __future__ import annotations

from fastapi import APIRouter

from app.infrastructure.reports.step_report import build_positioning_trace


router = APIRouter(prefix="/api/v1", tags=["Stable v1"])


@router.get("/sessions/{session_id}/positioning-trace")
async def get_positioning_trace(session_id: str) -> dict[str, object]:
    """Return persisted step reports and stage coverage for one session.

    This is a read-only API projection. It exposes saved stage summaries and
    artifact references; it does not expose hidden model reasoning or create
    any fallback planning output.
    """

    return await build_positioning_trace(session_id)

