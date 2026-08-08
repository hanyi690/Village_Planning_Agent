"""P1: lifespan must call shutdown_database (not just dispose_async_engine)."""
import pytest


@pytest.mark.asyncio
async def test_lifespan_calls_shutdown_database(monkeypatch):
    called = {"shutdown_database": False, "dispose_async_engine": False}

    async def fake_shutdown_database():
        called["shutdown_database"] = True

    async def fake_dispose():
        called["dispose_async_engine"] = True

    monkeypatch.setattr("app.database.shutdown_database", fake_shutdown_database, raising=False)
    monkeypatch.setattr("app.database.dispose_async_engine", fake_dispose, raising=False)
    monkeypatch.setattr("app.main.shutdown_database", fake_shutdown_database, raising=False)
    monkeypatch.setattr("app.main.dispose_async_engine", fake_dispose, raising=False)

    from app.main import app
    async with app.router.lifespan_context(app):
        pass

    assert called["dispose_async_engine"] is True
    assert called["shutdown_database"] is True, "lifespan must call shutdown_database()"
