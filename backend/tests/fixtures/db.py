"""Shared database + pipeline-state fixtures.

- ``sqlite_db``: temp-file SQLite patched onto ``app.database.engine`` globals
  (single patch point covers operations / report_store / bundle_store).
- ``pipeline_reset``: clears the in-process caches and singletons that the
  runtime data pipeline depends on (session bundle cache, KGManager,
  BundleStore, ConnectionRegistry).
- ``make_session_with_uploads``: async helper that persists a planning session
  plus uploaded files through the real ``app.database.operations`` layer.

Import path: fixtures are exposed to pytest via ``tests/conftest.py``
(``pytest_plugins``), so tests just ``from tests.fixtures.db import ...`` or
request the fixture by name.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

pytest.importorskip("fastapi")


# ── pytest fixtures ────────────────────────────────────────────────


@pytest.fixture
def sqlite_db(tmp_path, monkeypatch):
    """Patch engine globals to an isolated temp-file SQLite.

    Returns ``(setup, teardown)``: the caller drives engine creation inside
    the test's event loop. ``get_async_session()`` reads the patched module
    globals at call time, so every consumer (operations, ReportStore,
    BundleStore) transparently uses this database.

    Yields:
        (setup, teardown): ``setup() -> AsyncEngine``, ``teardown()`` disposes.
    """
    import app.database.engine as eng
    from sqlalchemy import event
    from sqlmodel import SQLModel

    state: Dict[str, Any] = {"engine": None}
    db_path = tmp_path / "test.db"

    async def setup():
        engine = create_async_engine(
            f"sqlite+aiosqlite:///{db_path}",
            connect_args={"check_same_thread": False},
        )

        @event.listens_for(engine.sync_engine, "connect")
        def _enable_fk(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        async with engine.begin() as conn:
            await conn.run_sync(SQLModel.metadata.create_all)
        state["engine"] = engine
        monkeypatch.setattr(eng, "async_engine", engine)
        monkeypatch.setattr(
            eng,
            "AsyncSessionLocal",
            async_sessionmaker(bind=engine, expire_on_commit=False),
        )
        return engine

    async def teardown():
        if state["engine"] is not None:
            await state["engine"].dispose()
            state["engine"] = None

    yield setup, teardown


@pytest.fixture
def pipeline_reset():
    """Reset in-process pipeline state before and after a test.

    The runtime pipeline keeps process-level caches/singletons:
      * ``app.services.session_bundle._bundle_cache``
      * ``app.modules.kg.manager.KGManager._instance``
      * ``app.services.bundle_store.BundleStore._instance``
      * ``app.modules.data.connections.base.ConnectionRegistry._connections``
    Clear them so a test observes a clean pipeline and does not leak state
    into the next one.
    """
    def _reset() -> None:
        import app.modules.data.connections.base as conn_base
        import app.modules.kg.manager as kg_man
        import app.services.bundle_store as bs
        import app.services.session_bundle as sb

        sb._bundle_cache.clear()
        kg_man.KGManager._instance = None
        bs.BundleStore._instance = None
        conn_base.ConnectionRegistry._connections.clear()

    _reset()
    yield
    _reset()


# ── async helpers (use inside test coroutines) ─────────────────────


async def make_session_with_uploads(
    session_id: str = "sess-e2e-001",
    village_name: str = "金田村",
    uploads: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """Create a planning session + uploaded files via the real operations layer.

    Args:
        session_id: Session identifier.
        village_name: Village used for session + Geocode-inferred config.
        uploads: List of upload payload dicts; each ``{file_category, filename,
            content_type, parsed_text?, gis_data?, gis_data_type?}``. Defaults
            to one document upload plus one boundary GeoJSON upload.

    Returns:
        The created ``session_id``.
    """
    from app.database.operations import (
        create_planning_session_async,
        create_uploaded_file_async,
    )

    await create_planning_session_async({
        "session_id": session_id,
        "project_name": f"{village_name}村庄规划",
        "village_data": f"{village_name}人口 500 人，面积 3.2 平方公里",
        "task_description": "编制村庄规划",
        "constraints": "不占用基本农田",
        "config": {
            "village_name": village_name,
            "province": "广东省",
            "city": "肇庆市",
            "county": "广宁县",
            "township": "排沙镇",
            "planning_period": "2022-2035年",
        },
    })

    if uploads is None:
        uploads = [
            {
                "file_category": "village_data",
                "filename": "村情调研.md",
                "original_filename": "村情调研.md",
                "content_type": "text/markdown",
                "file_type": "md",
                "parsed_text": "地形以丘陵为主，主导产业为水稻种植。",
            },
            {
                "file_category": "gis_data",
                "filename": "upload_boundary.geojson",
                "original_filename": "upload_boundary.geojson",
                "content_type": "application/geo+json",
                "file_type": "geojson",
                "gis_data_type": "boundary",
                "gis_data": {
                    "type": "FeatureCollection",
                    "features": [
                        {
                            "type": "Feature",
                            "properties": {"name": "村界"},
                            "geometry": {
                                "type": "Polygon",
                                "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]],
                            },
                        }
                    ],
                },
            },
        ]

    for i, u in enumerate(uploads):
        await create_uploaded_file_async(
            session_id=session_id,
            file_category=u.get("file_category", "document"),
            file_type=u.get("file_type", "unknown"),
            filename=u.get("filename", f"file_{i}"),
            original_filename=u.get("original_filename", u.get("filename", f"file_{i}")),
            file_size=u.get("file_size", 0),
            content_type=u.get("content_type", "application/octet-stream"),
            parsed_text=u.get("parsed_text"),
            gis_data=u.get("gis_data"),
            gis_data_type=u.get("gis_data_type"),
            parse_status=u.get("parse_status", "success"),
            parse_error=u.get("parse_error"),
        )

    return session_id
