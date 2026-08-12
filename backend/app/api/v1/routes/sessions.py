"""Session lifecycle transport: create and resume."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.contracts import ResumeAccepted, SessionCreated
from app.api.v1.session_create import create_session
from . import resume_session


router = APIRouter(prefix="/api/v1", tags=["Stable v1"])

router.add_api_route(
    "/sessions",
    create_session,
    methods=["POST"],
    response_model=SessionCreated,
    status_code=201,
    summary="Create a planning session",
)

router.add_api_route(
    "/sessions/{session_id}/resume",
    resume_session,
    methods=["POST"],
    response_model=ResumeAccepted,
)


__all__ = ["create_session", "resume_session", "router"]
