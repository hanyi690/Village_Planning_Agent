"""Regression tests for the application-owned async database lifecycle."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import text

from app.database import engine as database_engine


@pytest.fixture
def isolated_database(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    database_path = tmp_path / "lifecycle.db"
    monkeypatch.setattr(database_engine, "DB_PATH", database_path)
    return database_path


@pytest.mark.asyncio
async def test_dispose_resets_engine_and_session_factory(isolated_database: Path):
    await database_engine.shutdown_database()

    first_engine = await database_engine.get_async_engine()
    async with database_engine.get_async_session() as session:
        await session.execute(text("SELECT 1"))

    await database_engine.dispose_async_engine()

    assert database_engine.async_engine is None
    assert database_engine.AsyncSessionLocal is None

    second_engine = await database_engine.get_async_engine()
    assert second_engine is not first_engine
    await database_engine.shutdown_database()


@pytest.mark.asyncio
async def test_session_scope_does_not_implicitly_commit(isolated_database: Path):
    await database_engine.shutdown_database()
    engine = await database_engine.get_async_engine()
    async with engine.begin() as connection:
        await connection.execute(text("CREATE TABLE entries (value TEXT NOT NULL)"))

    async with database_engine.get_async_session() as session:
        await session.execute(text("INSERT INTO entries (value) VALUES ('uncommitted')"))

    async with database_engine.get_async_session() as session:
        result = await session.execute(text("SELECT COUNT(*) FROM entries"))
        assert result.scalar_one() == 0

    await database_engine.shutdown_database()


@pytest.mark.asyncio
async def test_session_scope_rolls_back_on_exception(isolated_database: Path):
    await database_engine.shutdown_database()
    engine = await database_engine.get_async_engine()
    async with engine.begin() as connection:
        await connection.execute(text("CREATE TABLE entries (value TEXT NOT NULL)"))

    with pytest.raises(RuntimeError, match="rollback marker"):
        async with database_engine.get_async_session() as session:
            await session.execute(text("INSERT INTO entries (value) VALUES ('rolled back')"))
            raise RuntimeError("rollback marker")

    async with database_engine.get_async_session() as session:
        result = await session.execute(text("SELECT COUNT(*) FROM entries"))
        assert result.scalar_one() == 0

    await database_engine.shutdown_database()
