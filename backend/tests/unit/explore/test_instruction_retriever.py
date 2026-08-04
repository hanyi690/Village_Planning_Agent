"""Instruction retriever tests - 【INSTRUCTION】 sections as structured evidence."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch

from app.agent.explore.retrievers.instruction_retriever import retrieve_from_instructions


@pytest.mark.asyncio
async def test_extracts_instruction_section_as_facts():
    fake_reports = {
        1: {
            "land_use": {
                "content": "报告正文\n【INSTRUCTION】\n位置：田坑自然村东侧\n面积：50公顷",
                "summary": "",
            },
        },
    }
    with patch(
        "app.agent.explore.retrievers.instruction_retriever.ReportStore"
    ) as mock_store_cls:
        store = mock_store_cls.get_instance.return_value
        store.get_layer_reports_with_sources = AsyncMock(
            side_effect=lambda sid, layer: fake_reports.get(layer, {})
        )
        facts, sources = await retrieve_from_instructions("s1", "land_use", "L1")
    assert any("田坑" in f.statement or "50" in f.statement for f in facts)
    assert any(s.source_type == "report" for s in sources)


@pytest.mark.asyncio
async def test_skips_reports_without_instruction():
    fake_reports = {
        1: {"land_use": {"content": "无指令段的报告", "summary": ""}},
    }
    with patch(
        "app.agent.explore.retrievers.instruction_retriever.ReportStore"
    ) as mock_store_cls:
        store = mock_store_cls.get_instance.return_value
        store.get_layer_reports_with_sources = AsyncMock(
            side_effect=lambda sid, layer: fake_reports.get(layer, {})
        )
        facts, sources = await retrieve_from_instructions("s1", "land_use", "L1")
    assert facts == []
