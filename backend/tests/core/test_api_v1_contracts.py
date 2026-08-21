"""Contract tests for the stable frontend-facing API."""

from __future__ import annotations

from datetime import datetime, timezone

import fastapi
import pytest
from fastapi import FastAPI
from pydantic import TypeAdapter, ValidationError

from app.api.v1.contracts import MapLayer, PublicEvent, SessionProjection
from app.application.projections.events import public_event
from app.api.routes import v1_router as router


def test_fastapi_is_pinned_to_requested_release() -> None:
    assert fastapi.__version__ == '0.141.1'


def test_v1_routes_are_in_openapi() -> None:
    app = FastAPI()
    app.include_router(router)
    paths = app.openapi()['paths']
    assert '/api/v1/sessions' in paths
    assert '/api/v1/sessions/{session_id}/state' in paths
    assert '/api/v1/sessions/{session_id}/delivery' in paths
    assert '/api/v1/sessions/{session_id}/map-layers' in paths
    assert '/api/v1/sessions/{session_id}/events' in paths
    assert '/api/v1/sessions/{session_id}/events/sync' in paths
    assert '/api/v1/sessions/{session_id}/human-review' in paths
    assert '/api/v1/sessions/{session_id}/evidence/query' in paths
    assert '/api/v1/projects' in paths


def test_public_dtos_forbid_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        MapLayer.model_validate({
            'layer_type': 'planned',
            'layer_name': 'planned_landuse',
            'geojson': {'type': 'FeatureCollection', 'features': []},
            'legacy_payload': {},
        })


def test_public_events_use_discriminator_and_strict_payloads() -> None:
    adapter = TypeAdapter(PublicEvent)
    event = adapter.validate_python({
        'schema_version': '1.0',
        'event_id': 's1:1',
        'seq': 1,
        'session_id': 's1',
        'occurred_at': datetime.now(timezone.utc),
        'type': 'completed',
        'data': {'delivery_status': 'partial'},
    })
    assert event.type == 'completed'

    with pytest.raises(ValidationError):
        adapter.validate_python({
            'schema_version': '1.0',
            'event_id': 's1:2',
            'seq': 2,
            'session_id': 's1',
            'occurred_at': datetime.now(timezone.utc),
            'type': 'unknown',
            'data': {},
        })


def test_legacy_event_is_projected_without_becoming_public_state() -> None:
    event = public_event('s1', {
        'type': 'layer_started',
        'seq': 3,
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'layer': 2,
    })
    assert event['type'] == 'progress'
    assert event['event_id'] == 's1:3'
    assert event['data']['layer'] == 2


def test_session_projection_rejects_non_contract_status() -> None:
    with pytest.raises(ValidationError):
        SessionProjection.model_validate({
            'session_id': 's1',
            'status': 'done-ish',
            'links': {
                'events': '/events',
                'event_sync': '/sync',
                'delivery': '/delivery',
                'map_layers': '/layers',
                'human_review': '/review',
                'artifacts': '/artifacts',
            },
        })
