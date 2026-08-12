from pathlib import Path
import asyncio

import pytest


@pytest.mark.asyncio
async def test_event_repository_persists_sequence_across_engine_restart(monkeypatch, tmp_path: Path):
    import app.database.engine as engine
    from app.infrastructure.events import EventRepository

    monkeypatch.setattr(engine, "DB_PATH", tmp_path / "events.db")
    monkeypatch.setattr(engine, "async_engine", None)
    monkeypatch.setattr(engine, "AsyncSessionLocal", None)
    await engine.init_async_db()

    first = await EventRepository.append("session-1", {"type": "started", "value": 1})
    second = await EventRepository.append("session-1", {"type": "completed", "value": 2})
    assert first["seq"] == 1
    assert second["seq"] == 2
    assert await EventRepository.last_seq("session-1") == 2

    await engine.dispose_async_engine()
    monkeypatch.setattr(engine, "async_engine", None)
    monkeypatch.setattr(engine, "AsyncSessionLocal", None)
    await engine.init_async_db()

    replay = await EventRepository.list_after("session-1", 1)
    assert replay == [{"type": "completed", "value": 2, "session_id": "session-1", "seq": 2}]

    concurrent = await asyncio.gather(*(
        EventRepository.append("session-2", {"type": "delta", "value": index})
        for index in range(8)
    ))
    assert sorted(item["seq"] for item in concurrent) == list(range(1, 9))
    await engine.shutdown_database()
