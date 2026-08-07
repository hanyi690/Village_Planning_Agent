"""Tests for ReportStore (dimension_reports persistence + versioning).

Covers the write/read path that the E2E pipeline depends on:
  save / bulk_save -> dimension_reports rows -> get_session_reports_async
  (grouped {layer: {dim_key: {...}}}), versioning, upsert semantics,
  knowledge-source round-trip and FK cascade cleanup.

Uses the shared ``sqlite_db`` fixture (tests/fixtures/db.py).
"""

import pytest

pytest.importorskip("fastapi")


@pytest.fixture
def report_session(sqlite_db):
    """Set up an isolated DB and return a function that yields a new session id."""
    setup, teardown = sqlite_db
    created = []

    async def make_session(sid="sess-rep"):
        from app.database.operations import create_planning_session_async

        await setup()
        await create_planning_session_async({"session_id": sid})
        created.append(sid)
        return sid

    async def cleanup():
        await teardown()

    return make_session, cleanup


async def _save(store, session_id, dim_key, version, content, layer=1, **kw):
    return await store.save(
        session_id=session_id, dim_key=dim_key, version=version,
        content=content, layer=layer, **kw,
    )


@pytest.mark.asyncio
async def test_save_and_get_by_report_id(report_session):
    from app.services.report_store import ReportStore

    make_session, cleanup = report_session
    sid = await make_session("sess-save")
    store = ReportStore()
    try:
        rid = await _save(store, sid, "location", 1, "## 区位\n丘陵地带")

        assert await store.get(rid) == "## 区位\n丘陵地带"
        record = await store.get_report(rid)
        assert record is not None
        assert record.session_id == sid
        assert record.dimension_key == "location"
        assert record.layer == 1
        assert record.version == 1
        assert record.summary  # structured JSON fallback summary
        assert record.generated_at is not None

        assert await store.get("missing-id") is None
    finally:
        await cleanup()


@pytest.mark.asyncio
async def test_version_increment_and_time_travel(report_session):
    from app.services.report_store import ReportStore

    make_session, cleanup = report_session
    sid = await make_session("sess-vers")
    store = ReportStore()
    try:
        await _save(store, sid, "land_use", 1, "v1: 耕地为主")
        rid2 = await _save(store, sid, "land_use", 2, "v2: 耕地+园地")

        assert await store.get_latest_version(sid, "land_use") == 2
        assert await store.get_latest(sid, "land_use") == "v2: 耕地+园地"
        assert await store.get_by_version(sid, "land_use", 1) == "v1: 耕地为主"
        assert await store.get_by_version(sid, "land_use", 3) is None

        by_ver = await store.get_report_by_version(sid, "land_use", 2)
        assert by_ver["content"] == "v2: 耕地+园地"
        assert by_ver["layer"] == 1
        assert by_ver["version"] == 2

        versions = await store.list_versions(sid, "land_use")
        assert [v["version"] for v in versions] == [1, 2]
        assert versions[1]["report_id"] == rid2

        latest = await store.get_latest_report(sid, "land_use")
        assert latest["content"] == "v2: 耕地+园地"
    finally:
        await cleanup()


@pytest.mark.asyncio
async def test_bulk_save_and_read_back_grouped(report_session):
    from datetime import datetime, timezone

    from app.database.operations import get_session_reports_async
    from app.services.report_store import ReportStore

    make_session, cleanup = report_session
    sid = await make_session("sess-bulk")
    store = ReportStore()
    try:
        now = datetime.now(timezone.utc)
        dims = ["location", "land_use", "traffic"]
        reports = [
            {
                "session_id": sid, "dimension_key": dims[i], "layer": 1,
                "version": 1, "report_id": f"r-bulk-{i}",
                "content": f"报告 {dims[i]}", "summary": "{}",
                "knowledge_sources": [{"source": f"doc-{dims[i]}", "chunk_count": 2}],
                "generated_at": now,
            }
            for i in range(3)
        ]
        ids = await store.bulk_save(reports)
        assert ids == [f"r-bulk-{i}" for i in range(3)]

        by_layer = await get_session_reports_async(sid)
        assert set(by_layer.keys()) == {1}
        assert set(by_layer[1].keys()) == set(dims)

        dim = by_layer[1]["location"]
        assert dim["report_id"] == "r-bulk-0"
        assert dim["content"] == "报告 location"
        assert dim["version"] == 1
        assert dim["generated_at"]

        with_sources = await store.get_layer_reports_with_sources(sid, 1)
        assert with_sources["location"]["knowledge_sources"] == [
            {"source": "doc-location", "chunk_count": 2}
        ]
        plain = await store.get_layer_reports(sid, 1)
        assert plain["location"] == "报告 location"
    finally:
        await cleanup()


@pytest.mark.asyncio
async def test_bulk_save_upsert_same_report_id(report_session):
    from app.database.operations import get_session_reports_async
    from app.services.report_store import ReportStore

    make_session, cleanup = report_session
    sid = await make_session("sess-upsert")
    store = ReportStore()
    try:
        base = {
            "session_id": sid, "dimension_key": "traffic", "layer": 1,
            "version": 1, "report_id": "r-upsert",
            "content": "旧内容", "summary": "{}",
        }
        await store.bulk_save([base])

        await store.bulk_save([{**base, "content": "新内容", "summary": "{}"}])

        assert await store.get("r-upsert") == "新内容"
        by_layer = await get_session_reports_async(sid)
        assert by_layer[1]["traffic"]["content"] == "新内容"

        record = await store.get_report("r-upsert")
        assert record is not None
    finally:
        await cleanup()


@pytest.mark.asyncio
async def test_bulk_save_is_idempotent_for_instruction_column(report_session):
    from app.services.report_store import ReportStore

    make_session, cleanup = report_session
    sid = await make_session("sess-instruction-idempotent")
    store = ReportStore()
    try:
        pending = {
            "session_id": sid, "dimension_key": "location", "layer": 1,
            "version": 1, "report_id": "r-instruction-idempotent",
            "content": (
                "正文\n\n【INSTRUCTION】\n"
                "| 类型 | 名称 | 位置 | 描述 | 规模 |\n"
                "| --- | --- | --- | --- | --- |\n"
                "| 现状分区 | 金田村 | 金田村 | 会话村名 | |\n"
            ),
            "summary": "{}",
        }
        await store.bulk_save([pending])
        # Simulates the second completion save after the first call split the
        # mutable pending dict into content + instruction.
        await store.bulk_save([pending])
        reports = await store.get_layer_reports_with_sources(sid, 1)
        assert reports["location"]["content"] == "正文"
        assert "【INSTRUCTION】" in (reports["location"]["instruction"] or "")
    finally:
        await cleanup()


@pytest.mark.asyncio
async def test_delete_session_reports(report_session):
    from app.database.operations import get_session_reports_async
    from app.services.report_store import ReportStore

    make_session, cleanup = report_session
    sid = await make_session("sess-del")
    store = ReportStore()
    try:
        await _save(store, sid, "location", 1, "## 区位")
        await _save(store, sid, "land_use", 1, "## 用地")
        assert len((await get_session_reports_async(sid)).get(1, {})) == 2

        deleted = await store.delete_session_reports(sid)
        assert deleted == 2
        assert await get_session_reports_async(sid) == {}
    finally:
        await cleanup()


@pytest.mark.asyncio
async def test_get_layer_summaries_parses_structured(report_session):
    from app.services.report_store import ReportStore

    make_session, cleanup = report_session
    sid = await make_session("sess-sum")
    store = ReportStore()
    try:
        await _save(store, sid, "location", 1, "## 区位\n丘陵")
        await _save(store, sid, "location", 2, "## 区位 v2\n台地")

        summaries = await store.get_layer_summaries(sid, 1)
        assert set(summaries.keys()) == {"location"}
        parsed = summaries["location"]
        assert parsed["dimension_key"] == "location"
        assert parsed["layer"] == 1
        assert parsed["word_count"] == len("## 区位 v2\n台地")
        assert "text_summary" in parsed
    finally:
        await cleanup()


@pytest.mark.asyncio
async def test_reports_cascade_on_session_delete(report_session):
    from app.database.operations import (
        delete_planning_session_async,
        get_session_reports_async,
    )
    from app.services.report_store import ReportStore

    make_session, cleanup = report_session
    sid = await make_session("sess-cascade")
    store = ReportStore()
    try:
        await _save(store, sid, "location", 1, "## 区位")
        assert (await get_session_reports_async(sid)).get(1, {})

        await delete_planning_session_async(sid)
        assert await get_session_reports_async(sid) == {}
    finally:
        await cleanup()
