"""Post-L3 resume service (Wave N P5) — targets the MAIN graph.

``resume_post_l3_chain`` resumes a paused planning session through
``PlanningRuntimeService.resume_from_interrupt`` (the official
``Command(resume=...)`` pattern against ``create_unified_planning_graph``),
collects the final AgentState and persists a JSON snapshot.
All heavy I/O is mocked: no LLM, no DB, no LangGraph run.
"""
from __future__ import annotations

import pytest

import app.services.post_l3_resume as resumemod
from app.services.post_l3_resume import resume_post_l3_chain
from app.services.runtime import PlanningRuntimeService


def _fake_final_state() -> dict:
    return {
        "session_id": "s1",
        "delivery_manifest": {"manifest_id": "m1"},
        "validation_report": {"passed": True},
        "reconciliation_report": {"consistent": True},
        "export_result": {"status": "completed"},
        "human_review_items": [{"request_id": "pr-1"}],
        "human_review_decisions": {"action": "approve"},
        "status": "delivered",
    }


class _FakeStore:
    def __init__(self, base_dir=".run-tmp"):
        self.saved = None

    def save(self, session_id, result):
        self.saved = (session_id, result)
        return {"session_id": session_id, "result": result}

    def get(self, session_id):
        return None


@pytest.mark.asyncio
async def test_resume_post_l3_chain_resumes_main_graph(monkeypatch):
    calls = []

    async def fake_resume_from_interrupt(session_id, decisions):
        calls.append((session_id, decisions))

    async def fake_aget_state_values(session_id):
        return _fake_final_state()

    async def fake_ensure_initialized():
        return None

    async def fake_aupdate_state(session_id, updates, as_node=None):
        return True

    fake_store = _FakeStore()

    monkeypatch.setattr(
        PlanningRuntimeService, "resume_from_interrupt", fake_resume_from_interrupt
    )
    monkeypatch.setattr(
        PlanningRuntimeService, "aget_state_values", fake_aget_state_values
    )
    monkeypatch.setattr(
        PlanningRuntimeService, "ensure_initialized", fake_ensure_initialized
    )
    monkeypatch.setattr(
        PlanningRuntimeService, "aupdate_state", fake_aupdate_state
    )
    monkeypatch.setattr(resumemod, "PostL3ResultStore", lambda: fake_store)

    result = await resume_post_l3_chain("s1", {"action": "approve"})

    assert calls == [("s1", {"action": "approve"})]
    assert result["session_id"] == "s1"
    assert result["status"] == "delivered"
    assert result["human_review_decisions"] == {"action": "approve"}
    assert result["delivery_manifest"] == {"manifest_id": "m1"}
    assert fake_store.saved == ("s1", result)


@pytest.mark.asyncio
async def test_resume_post_l3_chain_empty_state(monkeypatch):
    calls = []

    async def fake_resume_from_interrupt(session_id, decisions):
        calls.append((session_id, decisions))

    async def fake_aget_state_values(session_id):
        return None

    async def fake_ensure_initialized():
        return None

    async def fake_aupdate_state(session_id, updates, as_node=None):
        return True

    fake_store = _FakeStore()

    monkeypatch.setattr(
        PlanningRuntimeService, "resume_from_interrupt", fake_resume_from_interrupt
    )
    monkeypatch.setattr(
        PlanningRuntimeService, "aget_state_values", fake_aget_state_values
    )
    monkeypatch.setattr(
        PlanningRuntimeService, "ensure_initialized", fake_ensure_initialized
    )
    monkeypatch.setattr(
        PlanningRuntimeService, "aupdate_state", fake_aupdate_state
    )
    monkeypatch.setattr(resumemod, "PostL3ResultStore", lambda: fake_store)

    result = await resume_post_l3_chain("s1", {"action": "reject"})

    assert calls == [("s1", {"action": "reject"})]
    assert result["session_id"] == ""
    assert result["status"] == ""


@pytest.mark.asyncio
async def test_resume_writeback_uses_human_review_node(monkeypatch):
    update_kwargs = {}

    async def fake_resume_from_interrupt(session_id, decisions):
        return None

    async def fake_aget_state_values(session_id):
        return _fake_final_state()

    async def fake_ensure_initialized():
        return None

    async def fake_aupdate_state(session_id, updates, as_node=None):
        update_kwargs["as_node"] = as_node
        return True

    fake_store = _FakeStore()

    monkeypatch.setattr(
        PlanningRuntimeService, "resume_from_interrupt", fake_resume_from_interrupt
    )
    monkeypatch.setattr(
        PlanningRuntimeService, "aget_state_values", fake_aget_state_values
    )
    monkeypatch.setattr(
        PlanningRuntimeService, "ensure_initialized", fake_ensure_initialized
    )
    monkeypatch.setattr(
        PlanningRuntimeService, "aupdate_state", fake_aupdate_state
    )
    monkeypatch.setattr(resumemod, "PostL3ResultStore", lambda: fake_store)

    result = await resume_post_l3_chain("s1", {"action": "approve"})

    assert result["status"] == "delivered"
    assert update_kwargs.get("as_node") == "human_review"
