"""Tests for the shared dimension runtime helpers.

These helpers were extracted from ``app.agent.l1_observe.analysis_node``
(Wave D) so the new L2 strategize worker can reuse them. Each test mocks
the I/O dependencies (sse_manager, RagService, ReportStore, summary
generator, step_report service) so the helpers are exercised in isolation.
"""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agent.common import dimension_runtime as dr


@pytest.mark.asyncio
async def test_generate_summary_returns_json_string():
    with patch(
        "app.modules.parsing.summary_generator.generate_structured_summary",
        new=AsyncMock(
            return_value='{"dimension_key":"land_use","layer":1,"word_count":0,"text_summary":""}'
        ),
    ):
        out = await dr.generate_summary("land_use", 1, "测试内容")
    assert isinstance(out, str)
    assert json.loads(out)["dimension_key"] == "land_use"


@pytest.mark.asyncio
async def test_generate_summary_falls_back_on_error():
    with patch(
        "app.modules.parsing.summary_generator.generate_structured_summary",
        new=AsyncMock(side_effect=RuntimeError("boom")),
    ):
        out = await dr.generate_summary("land_use", 1, "测试内容")
    parsed = json.loads(out)
    assert parsed["dimension_key"] == "land_use"
    assert parsed["layer"] == 1


@pytest.mark.asyncio
async def test_publish_dimension_start_publishes_payload():
    with patch("app.services.sse.sse_manager.publish", new=AsyncMock()) as mock_pub:
        await dr.publish_dimension_start("s1", "land_use", "用地", 1, False)
    mock_pub.assert_awaited_once()
    payload = mock_pub.await_args.args[1]
    assert payload["type"] == "dimension_start"
    assert payload["dimension_key"] == "land_use"
    assert payload["dimension_name"] == "用地"
    assert payload["layer"] == 1
    assert payload["is_revision"] is False


@pytest.mark.asyncio
async def test_publish_dimension_complete_publishes_parsed_summary():
    with patch("app.services.sse.sse_manager.publish", new=AsyncMock()) as mock_pub:
        await dr.publish_dimension_complete(
            "s1", "land_use", "用地", 10, '{"dimension_key":"land_use"}', "rid", 2, 1, False,
        )
    payload = mock_pub.await_args.args[1]
    assert payload["type"] == "dimension_complete"
    assert payload["structured_summary"] == {"dimension_key": "land_use"}
    assert payload["report_id"] == "rid"
    assert payload["version"] == 2
    assert payload["word_count"] == 10


@pytest.mark.asyncio
async def test_run_rag_noop_when_rag_query_empty():
    cfg = SimpleNamespace(rag_query="", prefer_doc_types=[], layer=1)
    state = {"session_id": "s1", "config": {}}
    with patch(
        "app.services.runtime.PlanningRuntimeService.aget_state_values",
        new=AsyncMock(return_value={}),
    ):
        ctx, rlog = await dr.run_rag("land_use", cfg, state)
    assert ctx == ""
    assert rlog is None


@pytest.mark.asyncio
async def test_run_rag_returns_context_and_log_when_enabled():
    cfg = SimpleNamespace(rag_query="村庄用地标准", prefer_doc_types=[], layer=1)
    fake_rag = MagicMock()
    fake_rag.generate_queries = AsyncMock(return_value=["村庄用地标准"])
    fake_rag.search = AsyncMock(
        return_value=[
            {
                "content": "村庄用地分类标准内容（超过50字以通过过滤）",
                "metadata": {"source": "doc1", "title": "用地标准"},
                "score": 0.9,
            }
        ]
    )
    state = {"session_id": "s1", "config": {}}
    with (
        patch(
            "app.services.runtime.PlanningRuntimeService.aget_state_values",
            new=AsyncMock(return_value={}),
        ),
        patch("app.modules.rag.service.RagService.get_instance", return_value=fake_rag),
        patch("app.modules.rag.service.RagService.format_for_prompt", return_value="【上下文】用地"),
        patch("app.services.sse.sse_manager.publish", new=AsyncMock()),
    ):
        ctx, rlog = await dr.run_rag("land_use", cfg, state)
    assert ctx == "【上下文】用地"
    assert rlog is not None
    assert rlog.rag_enabled is True
    assert rlog.total_results == 1
    assert len(rlog.retrieved_chunks) == 1


@pytest.mark.asyncio
async def test_save_report_immediate_calls_bulk_save():
    store = MagicMock()
    store.bulk_save = AsyncMock(return_value=["id"])
    pending = {"dimension_key": "land_use", "version": 1}
    await dr.save_report_immediate(store, pending)
    store.bulk_save.assert_awaited_once_with([pending])


@pytest.mark.asyncio
async def test_save_report_immediate_swallows_exceptions():
    store = MagicMock()
    store.bulk_save = AsyncMock(side_effect=RuntimeError("db down"))
    await dr.save_report_immediate(store, {"dimension_key": "land_use", "version": 1})


@pytest.mark.asyncio
async def test_save_step_report_calls_service():
    with patch(
        "app.services.step_report.save_step_report", new=AsyncMock(return_value=True)
    ) as mock_save:
        await dr.save_step_report(
            "s1", "L1",
            step_name="analyze_dimension:land_use",
            dimension_key="land_use",
            layer=1,
            is_revision=False,
            outputs={"word_count": 10},
            diagnostics={"kg_cognition": True},
        )
    mock_save.assert_awaited_once()
    kwargs = mock_save.await_args.kwargs
    assert kwargs["inputs"] == {"is_revision": False}
    assert kwargs["outputs"] == {"word_count": 10}
    assert kwargs["diagnostics"] == {"kg_cognition": True}


@pytest.mark.asyncio
async def test_save_step_report_swallows_exceptions():
    with patch(
        "app.services.step_report.save_step_report",
        new=AsyncMock(side_effect=RuntimeError("boom")),
    ):
        await dr.save_step_report(
            "s1", "L1", step_name="analyze_dimension:land_use",
            dimension_key="land_use", layer=1,
        )


@pytest.mark.asyncio
async def test_load_dependency_reports_layer1_no_deps():
    cfg = SimpleNamespace(depends_on=[], layer_depends_on=[], phase_depends_on=[])
    store = MagicMock()
    with patch("app.services.report_store.ReportStore.get_instance", return_value=store):
        deps, same_layer = await dr.load_dependency_reports("land_use", cfg, 1, "s1", False)
    assert deps == ""
    assert same_layer == ""


@pytest.mark.asyncio
async def test_load_dependency_reports_raises_when_deps_unrecoverable():
    cfg = SimpleNamespace(depends_on=["socio_economic"], layer_depends_on=[], phase_depends_on=[])
    store = MagicMock()
    store.get_latest = AsyncMock(return_value=None)
    store.get_latest_report = AsyncMock(return_value=None)
    with (
        patch("app.services.report_store.ReportStore.get_instance", return_value=store),
        patch("app.agent.common.dimension_runtime.asyncio.sleep", new=AsyncMock()),
    ):
        with pytest.raises(dr.DependencyError):
            await dr.load_dependency_reports("land_use", cfg, 1, "s1", False)
