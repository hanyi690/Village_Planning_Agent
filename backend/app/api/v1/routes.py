"""Stable frontend-facing projections over workflow and artifact state."""

from __future__ import annotations

import json
import asyncio
from collections.abc import AsyncIterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any
from uuid import uuid4

from fastapi import APIRouter, Header, HTTPException
from fastapi.sse import EventSourceResponse, ServerSentEvent
from pydantic import TypeAdapter

from app.api.human_review_routes import ResolveRequest, resolve_human_review
from app.api.v1.contracts import (
    DeliveryProjection,
    EventSyncResponse,
    HumanReviewDecision,
    HumanReviewProjection,
    MapLayer,
    MapLayerCollection,
    ResourceLinks,
    SessionProjection,
    PublicEvent,
)
from app.services.artifact_store import FilesystemArtifactStore
from app.services.runtime import PlanningRuntimeService
from app.services.sse import sse_manager

router = APIRouter(prefix='/api/v1', tags=['Stable v1'])
_PUBLIC_EVENT_ADAPTER = TypeAdapter(PublicEvent)



def _links(session_id: str) -> ResourceLinks:
    base = f'/api/v1/sessions/{session_id}'
    return ResourceLinks(
        events=f'{base}/events',
        event_sync=f'{base}/events/sync',
        delivery=f'{base}/delivery',
        map_layers=f'{base}/map-layers',
        human_review=f'{base}/human-review',
    )


def _latest_payload(session_id: str, artifact_type: str) -> dict[str, Any] | None:
    store = FilesystemArtifactStore()
    refs = [ref for ref in store.list_by_run(session_id) if ref.artifact_type == artifact_type]
    if not refs:
        return None
    payload = store.retrieve(refs[0])
    return payload if isinstance(payload, dict) else None


def _status(state: dict[str, Any]) -> str:
    if state.get('fatal_error'):
        return 'failed'
    if state.get('human_interrupt') or state.get('paused_stage'):
        return 'paused'
    if state.get('delivery_status'):
        return 'completed'
    value = str(state.get('status') or 'running')
    allowed = {'pending', 'running', 'paused', 'reviewing', 'revising', 'completed', 'failed'}
    return value if value in allowed else 'running'


def _progress(state: dict[str, Any]) -> float:
    if state.get('delivery_status'):
        return 100.0
    phase = str(state.get('phase') or '')
    return {'layer1': 15.0, 'layer2': 35.0, 'layer3': 55.0}.get(phase, 70.0 if phase else 0.0)


def _delivery_projection(session_id: str) -> DeliveryProjection:
    manifest = _latest_payload(session_id, 'DeliveryManifest')
    snapshot = _latest_payload(session_id, 'DeliverySpatialSnapshot')
    if not manifest:
        return DeliveryProjection(session_id=session_id, available=False)
    deliverables = list(manifest.get('deliverables') or [])
    return DeliveryProjection(
        session_id=session_id,
        available=True,
        delivery_status=manifest.get('delivery_status'),
        statutory_complete=bool(manifest.get('statutory_complete')),
        snapshot_checksum=str((snapshot or {}).get('checksum') or ''),
        deferral_summary=dict(manifest.get('deferral_summary') or {}),
        diagnostic_summary=dict(manifest.get('diagnostic_summary') or {}),
        deliverables=deliverables,
        downloads=[str(item.get('path')) for item in deliverables if item.get('path')],
    )


def _read_geojson(path: str) -> dict[str, Any]:
    if not path:
        return {'type': 'FeatureCollection', 'features': []}
    candidate = Path(path).resolve()
    if not candidate.is_file():
        return {'type': 'FeatureCollection', 'features': []}
    payload = json.loads(candidate.read_text(encoding='utf-8'))
    return payload if isinstance(payload, dict) else {'type': 'FeatureCollection', 'features': []}


def _layer(kind: str, name: str, ref: dict[str, Any]) -> MapLayer:
    return MapLayer(
        layer_type=kind,
        layer_name=name,
        crs=str(ref.get('crs') or ''),
        checksum=str(ref.get('checksum') or ''),
        feature_count=int(ref.get('feature_count') or 0),
        geojson=_read_geojson(str(ref.get('path') or '')),
    )


async def _review_projection(session_id: str) -> HumanReviewProjection:
    snapshot = await PlanningRuntimeService.aget_state(session_id)
    if not snapshot:
        raise HTTPException(status_code=404, detail='session not found')
    state = dict(snapshot.values or {})
    interrupt = dict(state.get('human_interrupt') or {})
    items = list(interrupt.get('items') or state.get('human_review_items') or [])
    return HumanReviewProjection(
        session_id=session_id,
        pending=bool(items or interrupt),
        event_id=interrupt.get('event_id'),
        paused_stage=str(interrupt.get('paused_stage') or state.get('paused_stage') or ''),
        items=items,
    )


def _public_event(session_id: str, event: dict[str, Any]) -> dict[str, Any]:
    seq = int(event.get('seq') or 0)
    event_type = str(event.get('type') or 'progress')
    public_type = 'progress'
    data: Any = dict(event)
    if event_type == 'completed':
        public_type = 'completed'
        data = {'delivery_status': event.get('delivery_status')}
    elif event_type == 'error':
        public_type = 'failed'
        data = {
            'schema_version': '1.0',
            'code': str(event.get('code') or 'EXECUTION_FAILED'),
            'message': str(event.get('message') or event.get('error') or 'execution failed'),
            'request_id': str(event.get('request_id') or uuid4()),
            'retryable': bool(event.get('retryable', False)),
            'details': {},
        }
    occurred_at = event.get('timestamp')
    if isinstance(occurred_at, str):
        try:
            occurred_at = datetime.fromisoformat(occurred_at.replace('Z', '+00:00'))
        except ValueError:
            occurred_at = None
    if not isinstance(occurred_at, datetime):
        occurred_at = datetime.now(timezone.utc)
    projected = {
        'schema_version': '1.0',
        'event_id': f'{session_id}:{seq}',
        'seq': seq,
        'session_id': session_id,
        'occurred_at': occurred_at,
        'type': public_type,
        'data': data,
    }
    validated = _PUBLIC_EVENT_ADAPTER.validate_python(projected)
    return _PUBLIC_EVENT_ADAPTER.dump_python(validated, mode='json')


@router.get('/sessions/{session_id}/state', response_model=SessionProjection)
async def get_state(session_id: str) -> SessionProjection:
    state = await PlanningRuntimeService.aget_state_values(session_id)
    if not state:
        raise HTTPException(status_code=404, detail='session not found')
    manifest = _latest_payload(session_id, 'DeliveryManifest') or {}
    return SessionProjection(
        session_id=session_id,
        status=_status(state),
        active_stage=str(state.get('paused_stage') or state.get('phase') or ''),
        phase=str(state.get('phase') or ''),
        progress=_progress(state),
        human_review_pending=bool(state.get('human_interrupt')),
        delivery_status=state.get('delivery_status') or manifest.get('delivery_status'),
        statutory_complete=bool(manifest.get('statutory_complete')),
        last_event_seq=sse_manager.get_last_seq(session_id),
        links=_links(session_id),
    )


@router.get('/sessions/{session_id}/delivery', response_model=DeliveryProjection)
async def get_delivery(session_id: str) -> DeliveryProjection:
    return _delivery_projection(session_id)


@router.get('/sessions/{session_id}/map-layers', response_model=MapLayerCollection)
async def get_map_layers(session_id: str) -> MapLayerCollection:
    snapshot = _latest_payload(session_id, 'DeliverySpatialSnapshot')
    if not snapshot:
        raise HTTPException(status_code=404, detail='delivery spatial snapshot not found')
    layers: list[MapLayer] = []
    for name, ref in (snapshot.get('current_layers') or {}).items():
        layers.append(_layer('current', str(name), ref))
    planned = snapshot.get('complete_planned_landuse')
    if planned:
        layers.append(_layer('planned', 'planned_landuse', planned))
    for name, ref in (snapshot.get('planned_overlay_layers') or {}).items():
        layers.append(_layer('overlay', str(name), ref))
    for name, ref in (snapshot.get('constraint_layers') or {}).items():
        layers.append(_layer('constraint', str(name), ref))
    return MapLayerCollection(
        session_id=session_id,
        snapshot_checksum=str(snapshot.get('checksum') or ''),
        delivery_status=snapshot.get('delivery_status'),
        layers=layers,
    )


@router.get('/sessions/{session_id}/human-review', response_model=HumanReviewProjection)
async def get_review(session_id: str) -> HumanReviewProjection:
    return await _review_projection(session_id)


@router.post('/sessions/{session_id}/human-review')
async def submit_review(session_id: str, decision: HumanReviewDecision) -> dict[str, Any]:
    payload = dict(decision.decisions)
    payload['action'] = decision.action
    return await resolve_human_review(
        session_id,
        ResolveRequest(decisions=payload, action=decision.action, event_id=decision.event_id),
    )


@router.get('/sessions/{session_id}/events/sync', response_model=EventSyncResponse)
async def sync_events(session_id: str, after: int = 0) -> EventSyncResponse:
    events = sse_manager.get_events_from_seq(session_id, after)
    last_seq = sse_manager.get_last_seq(session_id)
    oldest = min((int(event.get('seq') or 0) for event in events), default=last_seq)
    resync = after > 0 and last_seq > after and not events
    if events and oldest > after + 1:
        resync = True
    return EventSyncResponse(
        session_id=session_id,
        events=[] if resync else [_public_event(session_id, event) for event in events],
        last_seq=last_seq,
        resync_required=resync,
    )


@router.get('/sessions/{session_id}/events', response_class=EventSourceResponse)
async def stream_events(
    session_id: str,
    last_event_id: Annotated[int | None, Header()] = None,
) -> AsyncIterable[ServerSentEvent]:
    queue = await PlanningRuntimeService.subscribe_with_history(session_id)
    try:
        yield ServerSentEvent(comment='connected', retry=3000)
        if last_event_id is not None:
            sync = await sync_events(session_id, last_event_id)
            if sync.resync_required:
                yield ServerSentEvent(
                    data={'schema_version': '1.0', 'after': last_event_id},
                    event='resync_required',
                    id=str(sync.last_seq),
                    retry=3000,
                )
            else:
                for event in sync.events:
                    yield ServerSentEvent(
                        data=event,
                        event=str(event['type']),
                        id=str(event['seq']),
                        retry=3000,
                    )
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=15.0)
            except asyncio.TimeoutError:
                yield ServerSentEvent(comment='heartbeat')
                continue
            public = _public_event(session_id, event)
            yield ServerSentEvent(
                data=public,
                event=str(public['type']),
                id=str(public['seq']),
                retry=3000,
            )
            if public['type'] in {'completed', 'failed'}:
                break
    finally:
        await sse_manager.unsubscribe(session_id, queue)


__all__ = ['router']
