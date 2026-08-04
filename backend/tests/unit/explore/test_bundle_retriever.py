"""Bundle retriever tests - VillageBundle spatial group statistics."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from app.agent.explore.retrievers.bundle_retriever import retrieve_from_bundle


@pytest.mark.asyncio
async def test_returns_facts_from_group_stats():
    fake_bundle = MagicMock()
    fake_bundle.village_name = "田坑村"
    fake_stats = {
        "current_landuse": {"count": 50, "distribution": "耕地为主"},
        "facility": {"count": 8, "distribution": "集中在村中心"},
    }
    with patch(
        "app.agent.explore.retrievers.bundle_retriever.resolve_bundle",
        new=AsyncMock(return_value=fake_bundle),
    ), patch(
        "app.agent.explore.retrievers.bundle_retriever.group_stats",
        return_value=fake_stats,
    ):
        facts, sources = await retrieve_from_bundle("s1", ["parcels", "facilities"])
    assert any("current_landuse" in f.statement or "耕地" in f.statement for f in facts)
    assert any(s.source_type == "gis_layer" for s in sources)


@pytest.mark.asyncio
async def test_empty_scope_returns_empty():
    fake_bundle = MagicMock()
    with patch(
        "app.agent.explore.retrievers.bundle_retriever.resolve_bundle",
        new=AsyncMock(return_value=fake_bundle),
    ), patch(
        "app.agent.explore.retrievers.bundle_retriever.group_stats",
        return_value={},
    ):
        facts, sources = await retrieve_from_bundle("s1", [])
    assert facts == []
