"""Aggregated stable v1 routers (blueprint M9 split transport).

The flat ``routes.py`` module is shadowed by this package; handlers are split
per resource below.  ``resume_session`` is defined here (package namespace) so
tests that monkeypatch ``resume_workflow_service`` on this module keep working.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.api.v1.contracts import ResumeAccepted, ResumeRequest
from app.application.commands.resume_workflow import (
    ResumeConflictError,
    ResumeNotFoundError,
    ResumeRequestError,
    ResumeWorkflowCommand,
    resume_workflow_service,
)


async def resume_session(session_id: str, request: ResumeRequest) -> ResumeAccepted:
    try:
        result = await resume_workflow_service.execute(
            ResumeWorkflowCommand(
                session_id=session_id,
                mode=request.mode,
                event_id=request.event_id,
                action=request.action,
                feedback=request.feedback,
                checkpoint_id=request.checkpoint_id,
                replay_from_stage=request.replay_from_stage,
            )
        )
    except ResumeRequestError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ResumeNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ResumeConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return ResumeAccepted(
        session_id=result.session_id,
        mode=result.mode,
        status=result.status,
        checkpoint_id=result.checkpoint_id,
        branch_id=result.branch_id,
        resume_plan=result.resume_plan.model_dump(mode="json"),
    )


from . import artifacts, dependency_graph, delivery, events, evidence, history, human_review, map_layers, sessions, source_layers, state, trace  # noqa: E402,F401
from .artifacts import get_artifact, list_artifacts  # noqa: E402,F401
from .delivery import get_delivery  # noqa: E402,F401
from .events import stream_events, sync_events  # noqa: E402,F401
from .human_review import get_review, submit_review  # noqa: E402,F401
from .map_layers import get_map_layers  # noqa: E402,F401
from .state import get_state  # noqa: E402,F401

from app.api.v1.session_create import create_session  # noqa: E402,F401
from app.application.projections.delivery import delivery_projections  # noqa: E402,F401
from app.application.projections.events import public_event  # noqa: E402,F401
from app.application.projections.session import session_projections  # noqa: E402,F401
from app.application.queries.artifacts import artifact_queries  # noqa: E402,F401
from app.application.queries.run_events import run_event_queries  # noqa: E402,F401
from app.application.queries.workflow_state import load_workflow_state  # noqa: E402,F401
from app.application.commands.submit_human_review import (  # noqa: E402,F401
    submit_human_decision_service,
)


router = APIRouter()
router.include_router(sessions.router)
router.include_router(state.router)
router.include_router(events.router)
router.include_router(human_review.router)
router.include_router(delivery.router)
router.include_router(map_layers.router)
router.include_router(source_layers.router)
router.include_router(artifacts.router)
router.include_router(dependency_graph.router)
router.include_router(evidence.router)
router.include_router(history.router)
router.include_router(trace.router)


__all__ = [
    "artifact_queries",
    "create_session",
    "delivery_projections",
    "get_artifact",
    "list_artifacts",
    "get_delivery",
    "get_map_layers",
    "get_review",
    "get_state",
    "load_workflow_state",
    "public_event",
    "resume_session",
    "resume_workflow_service",
    "router",
    "run_event_queries",
    "session_projections",
    "stream_events",
    "submit_human_decision_service",
    "submit_review",
    "sync_events",
]
