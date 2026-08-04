"""retrieve_evidence service tests - orchestration + merge + no-candidate guard."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from app.modules.schema.contracts.evidence_contracts import (
    ExplorationRequest,
    SpatialCognitionEvidence,
)
from app.agent.explore.service import retrieve_evidence, render_evidence_prompt_section


@pytest.mark.asyncio
async def test_retrieve_evidence_returns_result_with_bundle_and_cognition(
    mock_bundle, mock_kg, mock_cognition,
):
    req = ExplorationRequest(
        run_id="r1",
        request_type="spatial_lookup",
        query="耕地分布",
        stage="L1",
        dimension_key="land_use",
        query_purpose="context_injection",
        entity_scope=["parcels"],
    )
    fake_reports = {
        1: {"land_use": {"content": "耕地120公顷，集中在田坑。", "summary": ""}},
    }
    with patch(
        "app.agent.explore.retrievers.report_retriever.ReportStore"
    ) as rs, patch(
        "app.agent.explore.retrievers.instruction_retriever.ReportStore"
    ) as is_, patch(
        "app.agent.explore.retrievers.kg_retriever.session_kg",
        return_value=mock_kg,
    ), patch(
        "app.agent.explore.retrievers.kg_retriever.get_village_cognition",
        return_value=mock_cognition,
    ), patch(
        "app.agent.explore.retrievers.bundle_retriever.resolve_bundle",
        new=AsyncMock(return_value=mock_bundle),
    ), patch(
        "app.agent.explore.retrievers.bundle_retriever.group_stats",
        return_value={"polygons": {"current_landuse": {"count": 50, "labels": {}}}},
    ):
        rs.get_instance.return_value.get_layer_reports_with_sources = AsyncMock(
            side_effect=lambda sid, layer: fake_reports.get(layer, {})
        )
        is_.get_instance.return_value.get_layer_reports_with_sources = AsyncMock(
            side_effect=lambda sid, layer: fake_reports.get(layer, {})
        )
        result = await retrieve_evidence(req, session_id="s1", village_name="田坑村")
    assert result.evidence_bundle.facts
    assert result.spatial_cognition is not None
    assert result.spatial_cognition.village_overview == "组团状分布"


@pytest.mark.asyncio
async def test_retrieve_evidence_no_candidate_fields(mock_bundle):
    """Guardrail: result must never contain candidate BSMs, bbox, or intent."""
    req = ExplorationRequest(
        run_id="r1", request_type="spatial_lookup", query="x",
        stage="L1", dimension_key="land_use",
    )
    with patch(
        "app.agent.explore.retrievers.report_retriever.ReportStore"
    ) as rs, patch(
        "app.agent.explore.retrievers.instruction_retriever.ReportStore"
    ) as is_, patch(
        "app.agent.explore.retrievers.kg_retriever.session_kg",
        return_value=None,
    ), patch(
        "app.agent.explore.retrievers.bundle_retriever.resolve_bundle",
        new=AsyncMock(return_value=mock_bundle),
    ), patch(
        "app.agent.explore.retrievers.bundle_retriever.group_stats",
        return_value={},
    ):
        rs.get_instance.return_value.get_layer_reports_with_sources = AsyncMock(return_value={})
        is_.get_instance.return_value.get_layer_reports_with_sources = AsyncMock(return_value={})
        result = await retrieve_evidence(req, session_id="s1", village_name="x")
    bundle = result.evidence_bundle
    assert not hasattr(bundle, "candidate_bsm_list")
    assert not hasattr(bundle, "candidate_bbox")
    assert not hasattr(bundle, "intent")
    for fact in bundle.facts:
        assert not hasattr(fact, "candidate_bsm_list")
        assert not hasattr(fact, "candidate_bbox")


def test_render_prompt_section_produces_markdown():
    from app.modules.schema.contracts.evidence_contracts import (
        EvidenceBundle, EvidenceFact, EvidenceSource,
    )
    bundle = EvidenceBundle(
        request="耕地分布",
        facts=[EvidenceFact(statement="耕地120ha", confidence=0.9)],
        sources=[EvidenceSource(source_type="kg", reference="session_kg")],
        confidence=0.85,
    )
    cognition = SpatialCognitionEvidence(
        village_overview="组团状",
        spatial_pattern="组团状",
        topology_facts=["道路连通田坑-黄竹"],
        kg_confidence=0.8,
    )
    section = render_evidence_prompt_section(bundle, cognition)
    assert "## EXPLORE 证据" in section
    assert "耕地120ha" in section
    assert "组团状" in section
    assert "道路连通田坑-黄竹" in section
