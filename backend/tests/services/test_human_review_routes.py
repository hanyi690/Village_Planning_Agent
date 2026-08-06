"""Unit tests for GET /api/human-review/{session_id} (Wave N P5).

Verifies that pending human-review items are read from the interrupt
payload (snapshot.tasks[].interrupts[].value) on the FIRST interrupt,
when the checkpoint state does not yet contain "human_review_items".
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.api.human_review_routes as human_review_routes
from app.api.human_review_routes import router as human_review_router
from app.services.runtime import PlanningRuntimeService


class FakeInterrupt:
    def __init__(self, value):
        self.value = value


class FakeTask:
    def __init__(self, interrupts):
        self.interrupts = interrupts


class FakeSnapshot:
    def __init__(self, values=None, tasks=None):
        self.values = values or {}
        self.tasks = tasks or ()


def _make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(human_review_router)
    return app


def _get(monkeypatch, snapshot, session_id="sess-1"):
    async def fake_aget_state(session_id):
        return snapshot

    monkeypatch.setattr(PlanningRuntimeService, "aget_state", fake_aget_state)
    return TestClient(_make_app()).get(f"/api/human-review/{session_id}")


def test_get_returns_items_from_interrupt_payload(monkeypatch):
    snapshot = FakeSnapshot(
        values={},
        tasks=[
            FakeTask(
                interrupts=[
                    FakeInterrupt(
                        value={
                            "human_review_items": [{"request_id": "r1"}],
                            "paused_stage": "select",
                            "reason": "post_l3_human_review",
                        }
                    )
                ]
            )
        ],
    )
    resp = _get(monkeypatch, snapshot)
    assert resp.status_code == 200
    body = resp.json()
    assert body["pending_items"] == [{"request_id": "r1"}]
    assert body["paused_stage"] == "select"
    assert body["count"] == 1


def test_get_returns_items_from_state_when_present(monkeypatch):
    snapshot = FakeSnapshot(values={"human_review_items": [{"request_id": "r2"}]})
    resp = _get(monkeypatch, snapshot)
    assert resp.status_code == 200
    body = resp.json()
    assert body["pending_items"] == [{"request_id": "r2"}]
    assert body["count"] == 1


def test_get_returns_empty_when_no_interrupt(monkeypatch):
    snapshot = FakeSnapshot(values={}, tasks=[])
    resp = _get(monkeypatch, snapshot)
    assert resp.status_code == 200
    body = resp.json()
    assert body["pending_items"] == []
    assert body["count"] == 0


def test_resolve_rejects_empty_decisions(monkeypatch):
    called = []

    async def fake_resume_post_l3_chain(session_id, decisions):
        called.append(decisions)
        return {}

    monkeypatch.setattr(human_review_routes, "resume_post_l3_chain", fake_resume_post_l3_chain)
    resp = TestClient(_make_app()).post(
        "/api/human-review/sess-1/resolve", json={"decisions": {}}
    )
    assert resp.status_code == 422
    assert called == []


def test_resolve_accepts_non_empty_decisions(monkeypatch):
    received = {}

    async def fake_resume_post_l3_chain(session_id, decisions):
        received["decisions"] = decisions
        return {"status": "done"}

    monkeypatch.setattr(human_review_routes, "resume_post_l3_chain", fake_resume_post_l3_chain)
    resp = TestClient(_make_app()).post(
        "/api/human-review/sess-1/resolve", json={"decisions": {"action": "approve"}}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["resolved"] is True
    assert received["decisions"] == {"action": "approve"}
