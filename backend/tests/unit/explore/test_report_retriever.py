"""Report retriever tests - search L1/L2/L3 AnalysisReports for evidence."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch

from app.agent.explore.retrievers.report_retriever import retrieve_from_reports


@pytest.mark.asyncio
async def test_retrieve_facts_from_layer_reports():
    """Should extract spatial findings as EvidenceFacts from report content."""
    fake_reports = {
        1: {
            "land_use": {"content": "耕地面积120公顷，集中在田坑自然村。", "summary": ""},
        },
    }
    with patch(
        "app.agent.explore.retrievers.report_retriever.ReportStore"
    ) as mock_store_cls:
        store = mock_store_cls.get_instance.return_value
        store.get_layer_reports_with_sources = AsyncMock(
            side_effect=lambda sid, layer: fake_reports.get(layer, {})
        )
        facts, sources = await retrieve_from_reports(
            session_id="s1",
            dimension_key="land_use",
            stage="L1",
        )
    assert any("120" in f.statement for f in facts)
    assert any(s.source_type == "report" for s in sources)


@pytest.mark.asyncio
async def test_retrieve_skips_empty_reports():
    with patch(
        "app.agent.explore.retrievers.report_retriever.ReportStore"
    ) as mock_store_cls:
        store = mock_store_cls.get_instance.return_value
        store.get_layer_reports_with_sources = AsyncMock(return_value={})
        facts, sources = await retrieve_from_reports("s1", "land_use", "L1")
    assert facts == []
    assert sources == []
