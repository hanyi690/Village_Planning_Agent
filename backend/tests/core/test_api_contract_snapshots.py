"""Ensure committed frontend contracts cannot silently drift."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI
from pydantic import TypeAdapter

from app.api.v1 import router
from app.api.v1.contracts import PublicEvent


ROOT = Path(__file__).resolve().parents[3]


def test_openapi_v1_snapshot_is_current() -> None:
    app = FastAPI(title='Village Planning Stable API', version='1.0.0', openapi_version='3.1.0')
    app.include_router(router)
    stored = json.loads((ROOT / 'docs/contracts/openapi-v1.json').read_text(encoding='utf-8'))
    assert stored == app.openapi()


def test_sse_schema_snapshot_is_current() -> None:
    stored = json.loads(
        (ROOT / 'docs/contracts/sse-events-v1.schema.json').read_text(encoding='utf-8')
    )
    assert stored == TypeAdapter(PublicEvent).json_schema()
