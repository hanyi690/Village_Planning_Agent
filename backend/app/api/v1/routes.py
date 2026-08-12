"""Stable frontend-facing transport for application projections and commands."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterable
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException
from fastapi.sse import EventSourceResponse, ServerSentEvent

from app.api.v1.contracts import (
    DeliveryProjection,
    EventSyncResponse,
    HumanReviewDecision,
    HumanReviewProjection,
    MapLayerCollection,
    PublicEvent,
    ResumeAccepted,
    ResumeRequest,
    SessionCreated,
    SessionProjection,
)
from app.api.v1.session_create import create_session
from app.application.commands.resume_workflow import (
    ResumeConflictError,
    ResumeNotFoundError,
    ResumeRequestError,
    ResumeWorkflowCommand,
    resume_workflow_service,
)
from app.application.commands.submit_human_review import (
    HumanDecisionConflictError,
    HumanDecisionNotFoundError,
    SubmitHumanDecisionCommand,
    submit_human_decision_service,
)
from app.application.projections.delivery import delivery_projections
from app.application.projections.events import public_event
from app.application.projections.session import ProjectionNotFoundError, session_projections
from app.application.queries.artifacts import ArtifactNotFoundError, artifact_queries
from app.application.queries.run_events import run_event_queries
from app.application.queries.workflow_state import load_workflow_state


router = APIRouter(prefix='/api/v1', tags=['Stable v1'])

router.add_api_route(
    '/sessions',
    create_session,
    methods=['POST'],
    response_model=SessionCreated,
    status_code=201,
    summary="Create a planning session",
)


def _as_public(model: object, public_type: type) -> object:
    return public_type.model_validate(model.model_dump(mode="python"))


@router.get('/sessions/{session_id}/state', response_model=SessionProjection)
async def get_state(session_id: str) -> SessionProjection:
    state = await load_workflow_state(session_id)
    try:
        view = await session_projections.get(session_id, state=state)
    except ProjectionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _as_public(view, SessionProjection)


@router.get('/sessions/{session_id}/delivery', response_model=DeliveryProjection)
async def get_delivery(session_id: str) -> DeliveryProjection:
    try:
        view = await delivery_projections.get(session_id)
    except ProjectionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _as_public(view, DeliveryProjection)


@router.get('/sessions/{session_id}/map-layers', response_model=MapLayerCollection)
async def get_map_layers(session_id: str) -> MapLayerCollection:
    try:
        view = await delivery_projections.map_layers(session_id)
    except ProjectionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _as_public(view, MapLayerCollection)


@router.get('/sessions/{session_id}/artifacts/{artifact_key}')
async def get_artifact(session_id: str, artifact_key: str) -> dict[str, object]:
    try:
        artifact = await artifact_queries.read(session_id, artifact_key)
    except ArtifactNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if artifact is None:
        raise HTTPException(status_code=404, detail="artifact is not present in current checkpoint")
    return artifact.model_dump(mode="json")


@router.get('/sessions/{session_id}/human-review', response_model=HumanReviewProjection)
async def get_review(session_id: str) -> HumanReviewProjection:
    try:
        view = await session_projections.human_review(session_id)
    except ProjectionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _as_public(view, HumanReviewProjection)


@router.post('/sessions/{session_id}/human-review')
async def submit_review(session_id: str, decision: HumanReviewDecision) -> dict[str, object]:
    try:
        result = await submit_human_decision_service.execute(
            SubmitHumanDecisionCommand(
                session_id=session_id,
                event_id=decision.event_id,
                action=decision.action,
                decisions=dict(decision.decisions),
            )
        )
    except HumanDecisionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except HumanDecisionConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return result.model_dump(mode="json")


@router.post('/sessions/{session_id}/resume', response_model=ResumeAccepted)
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


@router.get('/sessions/{session_id}/events/sync', response_model=EventSyncResponse)
async def sync_events(session_id: str, after: int = 0) -> EventSyncResponse:
    sync = await run_event_queries.sync(session_id, after)
    return EventSyncResponse(
        session_id=session_id,
        events=[public_event(session_id, event) for event in sync.events],
        last_seq=sync.last_seq,
        resync_required=sync.resync_required,
    )


@router.get('/sessions/{session_id}/events', response_class=EventSourceResponse)
async def stream_events(
    session_id: str,
    last_event_id: Annotated[int | None, Header()] = None,
) -> AsyncIterable[ServerSentEvent]:
    stream = await run_event_queries.open_stream(session_id, last_event_id or 0)
    queue = stream.queue
    delivered_seq = int(last_event_id or 0)

    def resync_event(after: int) -> ServerSentEvent:
        return ServerSentEvent(
            data={"schema_version": "1.0", "after": after},
            event="resync_required",
            id=str(after) if after > 0 else None,
            retry=3000,
        )

    try:
        yield ServerSentEvent(comment="connected", retry=3000)
        if stream.resync_required:
            yield resync_event(delivered_seq)
            return
        for event in stream.replay:
            projected = public_event(session_id, event)
            delivered_seq = max(delivered_seq, int(projected["seq"]))
            yield ServerSentEvent(
                data=projected,
                event=str(projected["type"]),
                id=str(projected["seq"]),
                retry=3000,
            )
            if projected["type"] in {"completed", "failed"}:
                return
        while True:
            if stream.needs_resync():
                yield resync_event(delivered_seq)
                return
            try:
                event = await asyncio.wait_for(queue.get(), timeout=15.0)
            except asyncio.TimeoutError:
                if stream.needs_resync():
                    yield resync_event(delivered_seq)
                    return
                yield ServerSentEvent(comment="heartbeat")
                continue
            if int(event.get("seq") or 0) <= delivered_seq:
                continue
            projected = public_event(session_id, event)
            delivered_seq = max(delivered_seq, int(projected["seq"]))
            yield ServerSentEvent(
                data=projected,
                event=str(projected["type"]),
                id=str(projected["seq"]),
                retry=3000,
            )
            if projected["type"] in {"completed", "failed"}:
                break
    finally:
        await run_event_queries.close_stream(session_id, queue)


__all__ = ["router"]
