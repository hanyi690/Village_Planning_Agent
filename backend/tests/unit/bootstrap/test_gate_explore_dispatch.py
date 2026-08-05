"""EXPLORE dispatch from gates tests."""

import pytest

from app.agent.explore.service import retrieve_evidence_for_gate


@pytest.mark.asyncio
async def test_retrieve_evidence_for_gate_translates_pending_requests(monkeypatch):
    """Gate EXPLORE -> retrieve_evidence_for_gate translates PendingRequests to ExplorationRequests."""
    captured = []

    async def fake_retrieve(request, session_id, village_name=""):
        captured.append(request)
        from types import SimpleNamespace
        return SimpleNamespace(evidence_bundle=None, spatial_cognition=None)

    monkeypatch.setattr(
        "app.agent.explore.service.retrieve_evidence", fake_retrieve
    )

    gate_decision = {
        "stage": "l1",
        "passed": False,
        "feedback_route": "EXPLORE",
        "pending_requests": [
            {
                "request_id": "pr-1",
                "stage": "explore",
                "request_type": "evidence_gap",
                "context": {"reason": "EXPLORE", "gap_id": "g1", "dimension": "land_use"},
            },
            {
                "request_id": "pr-2",
                "stage": "explore",
                "request_type": "source_lookup",
                "context": {"reason": "EXPLORE", "dimension": "traffic"},
            },
        ],
        "evidence_requests": ["missing data for land_use"],
    }

    await retrieve_evidence_for_gate(
        gate_decision, session_id="s1", village_name="金田村"
    )
    assert len(captured) == 2
    assert captured[0].request_type == "evidence_gap"
    assert captured[0].run_id == "s1"
    assert captured[1].request_type == "source_lookup"


@pytest.mark.asyncio
async def test_retrieve_evidence_for_gate_no_pending_requests(monkeypatch):
    """Gate with no pending_requests -> no evidence retrieval."""
    called = []

    async def fake_retrieve(request, session_id, village_name=""):
        called.append(request)

    monkeypatch.setattr(
        "app.agent.explore.service.retrieve_evidence", fake_retrieve
    )

    gate_decision = {
        "stage": "l1",
        "passed": False,
        "feedback_route": "EXPLORE",
        "pending_requests": [],
        "evidence_requests": [],
    }

    await retrieve_evidence_for_gate(
        gate_decision, session_id="s1", village_name="金田村"
    )
    assert len(called) == 0


@pytest.mark.asyncio
async def test_retrieve_evidence_for_gate_not_explore_route(monkeypatch):
    """Gate with non-EXPLORE route -> no evidence retrieval."""
    called = []

    async def fake_retrieve(request, session_id, village_name=""):
        called.append(request)

    monkeypatch.setattr(
        "app.agent.explore.service.retrieve_evidence", fake_retrieve
    )

    gate_decision = {
        "stage": "l1",
        "passed": True,
        "feedback_route": None,
        "pending_requests": [],
    }

    await retrieve_evidence_for_gate(
        gate_decision, session_id="s1", village_name="金田村"
    )
    assert len(called) == 0
