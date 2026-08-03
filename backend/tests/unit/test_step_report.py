"""P2-3 单元测试：StepReport 落库/查询/聚合。"""

import pytest

pytest.importorskip("fastapi")


@pytest.fixture
def step_db(sqlite_db):
    """临时 SQLite + 预置一个 planning session."""
    setup, teardown = sqlite_db

    async def _setup():
        # 确保所有 SQLModel 表已注册（含 StepReportModel）
        import app.database.models  # noqa: F401
        engine = await setup()
        from app.database.operations import create_planning_session_async

        await create_planning_session_async({
            "session_id": "sess-step-001",
            "project_name": "金田村规划",
            "village_data": "人口500人",
            "task_description": "编制规划",
            "constraints": "无",
        })
        return engine

    return _setup, teardown


@pytest.mark.asyncio
async def test_save_and_query_step_report(step_db):
    setup, teardown = step_db
    await setup()
    try:
        from app.services.step_report import (
            save_step_report,
            get_session_step_reports,
            build_positioning_trace,
        )

        ok = await save_step_report(
            "sess-step-001", "KG_PREBUILD",
            step_name="kg_prebuild",
            outputs={"triple_count": 39384},
            diagnostics={"sfTouches": 4102},
        )
        assert ok is True

        ok2 = await save_step_report(
            "sess-step-001", "L1",
            step_name="analyze_dimension:location",
            dimension_key="location",
            layer=1,
            outputs={"report_id": "abc123", "has_instruction": True},
        )
        assert ok2 is True

        reports = await get_session_step_reports("sess-step-001")
        assert len(reports) == 2
        stages = {r["stage"] for r in reports}
        assert stages == {"KG_PREBUILD", "L1"}

        # 过滤
        l1 = await get_session_step_reports("sess-step-001", stage="L1")
        assert len(l1) == 1
        assert l1[0]["dimension_key"] == "location"

        # 聚合
        trace = await build_positioning_trace("sess-step-001")
        assert "KG_PREBUILD" in trace["stages"]
        assert "location" in trace["by_dimension"]
    finally:
        await teardown()


@pytest.mark.asyncio
async def test_save_empty_session_returns_false(step_db):
    setup, teardown = step_db
    await setup()
    try:
        from app.services.step_report import save_step_report

        assert await save_step_report("", "L1") is False
    finally:
        await teardown()


@pytest.mark.asyncio
async def test_query_nonexistent_session(step_db):
    setup, teardown = step_db
    await setup()
    try:
        from app.services.step_report import get_session_step_reports

        reports = await get_session_step_reports("no-such-session")
        assert reports == []
    finally:
        await teardown()
