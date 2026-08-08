"""P1: HITL publish failure must not mark success; accept aliases approve."""
import pytest


@pytest.mark.asyncio
async def test_publish_failure_leaves_flag_false(monkeypatch):
    """When SSE publish fails, human_review_pause_published must be False."""
    from app.agent.bootstrap import graph

    async def boom_publish(session_id, event):
        raise RuntimeError("SSE unavailable")

    monkeypatch.setattr("app.services.sse.sse_manager.publish", boom_publish)

    state = {
        "session_id": "test-hitl-1",
        "human_review_items": [{"item": "test"}],
        "human_review_event_id": "evt-1",
        "paused_stage": "execute",
        "human_review_pause_published": False,
    }
    result = await graph.publish_human_review_pause(state)
    assert result.get("human_review_pause_published") is False, (
        "publish failure must not set human_review_pause_published=True"
    )


@pytest.mark.asyncio
async def test_publish_success_sets_flag_true(monkeypatch):
    """When SSE publish succeeds, human_review_pause_published must be True."""
    from app.agent.bootstrap import graph

    published = []

    async def fake_publish(session_id, event):
        published.append((session_id, event))

    monkeypatch.setattr("app.services.sse.sse_manager.publish", fake_publish)

    state = {
        "session_id": "test-hitl-2",
        "human_review_items": [{"item": "test"}],
        "human_review_event_id": "evt-2",
        "paused_stage": "execute",
        "human_review_pause_published": False,
    }
    result = await graph.publish_human_review_pause(state)
    assert result.get("human_review_pause_published") is True
    assert len(published) == 1


@pytest.mark.asyncio
async def test_accept_aliases_approve_in_resolve_request():
    """The resolve endpoint should accept 'approve' as equivalent to 'accept'."""
    from app.api.human_review_routes import ResolveRequest

    req = ResolveRequest(decisions={"action": "approve"}, action="approve")
    assert req.action in ("approve", "accept")

    req2 = ResolveRequest(decisions={"action": "accept"}, action="accept")
    assert req2.action in ("approve", "accept")


@pytest.mark.asyncio
async def test_retry_still_accepted():
    """The retry action must still be accepted (distinct semantics)."""
    from app.api.human_review_routes import ResolveRequest

    req = ResolveRequest(decisions={"action": "retry"}, action="retry")
    assert req.action == "retry"
