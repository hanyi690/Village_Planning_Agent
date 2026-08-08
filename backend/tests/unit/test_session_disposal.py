"""P1: session deletion must clean up all resource categories."""
import pytest


@pytest.mark.asyncio
async def test_delete_session_cleans_all_categories(monkeypatch):
    from app.services.session import SessionService

    cleaned = []

    async def fake_cancel_tasks(session_id):
        cleaned.append("tasks")
        return True

    async def fake_clear_context(session_id):
        cleaned.append("context")
        return True

    async def fake_delete_bundle(session_id):
        cleaned.append("bundle")
        return True

    async def fake_delete_kg(session_id):
        cleaned.append("kg")
        return True

    async def fake_delete_artifacts(session_id):
        cleaned.append("artifacts")
        return True

    async def fake_delete_checkpoint(session_id):
        cleaned.append("checkpoint")
        return True

    async def fake_clear_sse(session_id):
        cleaned.append("sse")
        return True

    async def fake_delete_db(session_id):
        cleaned.append("database")
        return True

    monkeypatch.setattr("app.services.session._cancel_session_tasks", fake_cancel_tasks)
    monkeypatch.setattr("app.services.session._clear_session_context", fake_clear_context)
    monkeypatch.setattr("app.services.session._delete_session_bundle", fake_delete_bundle)
    monkeypatch.setattr("app.services.session._delete_session_kg", fake_delete_kg)
    monkeypatch.setattr("app.services.session._delete_session_artifacts", fake_delete_artifacts)
    monkeypatch.setattr("app.services.session._delete_session_checkpoint", fake_delete_checkpoint)
    monkeypatch.setattr("app.services.session._clear_session_sse", fake_clear_sse)
    monkeypatch.setattr("app.services.session.delete_planning_session_async", fake_delete_db)

    result = await SessionService.delete_session("test-dispose-1", project_name="p")
    expected_keys = {
        "tasks", "context", "bundle", "kg", "artifacts",
        "checkpoint", "sse", "database",
    }
    assert set(result.keys()) >= expected_keys, (
        f"missing keys: {expected_keys - set(result.keys())}"
    )
    for key in expected_keys:
        assert result[key] is True, f"{key} cleanup failed"
    assert set(cleaned) == expected_keys


@pytest.mark.asyncio
async def test_delete_session_continues_after_partial_failure(monkeypatch):
    from app.services.session import SessionService

    async def boom_bundle(session_id):
        raise RuntimeError("bundle gone")

    async def ok(session_id):
        return True

    monkeypatch.setattr("app.services.session._cancel_session_tasks", ok)
    monkeypatch.setattr("app.services.session._clear_session_context", ok)
    monkeypatch.setattr("app.services.session._delete_session_bundle", boom_bundle)
    monkeypatch.setattr("app.services.session._delete_session_kg", ok)
    monkeypatch.setattr("app.services.session._delete_session_artifacts", ok)
    monkeypatch.setattr("app.services.session._delete_session_checkpoint", ok)
    monkeypatch.setattr("app.services.session._clear_session_sse", ok)
    monkeypatch.setattr("app.services.session.delete_planning_session_async", ok)

    result = await SessionService.delete_session("test-dispose-2", project_name="p")
    assert result["bundle"] is False
    assert result["database"] is True
