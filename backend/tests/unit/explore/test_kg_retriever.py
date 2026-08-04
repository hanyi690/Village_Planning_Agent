"""KG retriever tests - session KG cognition + topology facts."""
from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock

from app.agent.explore.retrievers.kg_retriever import retrieve_from_kg


@pytest.mark.asyncio
async def test_returns_facts_and_cognition_when_kg_available():
    fake_kg = MagicMock()
    fake_cognition = MagicMock()
    fake_cognition.semantic = {
        "context_block": {
            "overview": "田坑村组团状分布",
            "parcel_count": 50,
            "total_area_ha": 320.5,
            "spatial_pattern": "组团状",
        },
        "constraint_block": {"constraint_coverage": "生态红线30%"},
    }
    with patch(
        "app.agent.explore.retrievers.kg_retriever.session_kg",
        return_value=fake_kg,
    ), patch(
        "app.agent.explore.retrievers.kg_retriever.get_village_cognition",
        return_value=fake_cognition,
    ):
        facts, cognition = await retrieve_from_kg(
            "s1", "田坑村", "land_use", "L1"
        )
    assert cognition.village_overview == "田坑村组团状分布"
    assert cognition.spatial_pattern == "组团状"
    assert cognition.constraint_coverage == "生态红线30%"
    assert cognition.kg_confidence > 0


@pytest.mark.asyncio
async def test_returns_empty_when_kg_none():
    with patch(
        "app.agent.explore.retrievers.kg_retriever.session_kg",
        return_value=None,
    ):
        facts, cognition = await retrieve_from_kg("s1", "田坑村", "land_use", "L1")
    assert facts == []
    assert cognition.village_overview == ""
    assert cognition.kg_confidence == 0.0


@pytest.mark.asyncio
async def test_topology_facts_for_l3():
    fake_kg = MagicMock()
    fake_cognition = MagicMock()
    fake_cognition.semantic = {"context_block": {}, "constraint_block": {}}
    fake_roads = [{"name": "通村路A"}, {"name": "沿河路B"}]
    with patch(
        "app.agent.explore.retrievers.kg_retriever.session_kg",
        return_value=fake_kg,
    ), patch(
        "app.agent.explore.retrievers.kg_retriever.get_village_cognition",
        return_value=fake_cognition,
    ), patch(
        "app.agent.explore.retrievers.kg_retriever.query_kg",
        side_effect=lambda kg, tpl, **kw: fake_roads if tpl == "get_road_network" else [],
    ):
        facts, cognition = await retrieve_from_kg("s1", "田坑村", "spatial_structure", "L3")
    assert any("道路" in tf or "路" in tf for tf in cognition.topology_facts)
