"""Verify analyze_dimension migrated to the deterministic EXPLORE evidence service.

Wave C replaced the old `_optimize_semantics` + `_build_explore_brief` pair with
`retrieve_evidence` + `render_evidence_prompt_section`. This module proves:
  1. analyze_dimension actually calls retrieve_evidence (smoke, with heavy
     internal RAG/DB/SSE/LLM dependencies patched out),
  2. the module imports the new service at import time (structural, robust),
  3. the old functions are gone.
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.modules.schema.contracts.evidence_contracts import (
    ExplorationResult,
    EvidenceBundle,
    SpatialCognitionEvidence,
)


class _FakeLLM:
    async def astream(self, prompt):
        from langchain_core.messages import AIMessage

        yield AIMessage(content="测试输出")
        return


@pytest.mark.asyncio
async def test_analyze_dimension_calls_retrieve_evidence():
    fake_result = ExplorationResult(
        evidence_bundle=EvidenceBundle(request="x", facts=[], sources=[]),
        spatial_cognition=SpatialCognitionEvidence(village_overview="test"),
    )

    fake_rag = MagicMock()
    fake_rag.generate_queries = AsyncMock(return_value=["村庄用地标准"])
    fake_rag.search = AsyncMock(return_value=[])

    fake_store = MagicMock()
    fake_store.get_latest = AsyncMock(return_value=None)
    fake_store.get_latest_report = AsyncMock(return_value=None)
    fake_store.get_layer_reports = AsyncMock(return_value={})
    fake_store.get_layer_summaries = AsyncMock(return_value={})
    fake_store.get_latest_version = AsyncMock(return_value=0)
    fake_store.bulk_save = AsyncMock(return_value=None)

    with (
        patch(
            "app.agent.l1_observe.analysis_node.retrieve_evidence",
            new=AsyncMock(return_value=fake_result),
        ) as mock_retrieve,
        patch(
            "app.services.runtime.PlanningRuntimeService.aget_state_values",
            new=AsyncMock(return_value={}),
        ),
        patch(
            "app.modules.rag.service.RagService.get_instance",
            return_value=fake_rag,
        ),
        patch(
            "app.agent.l1_observe.analysis_node._get_llm",
            return_value=_FakeLLM(),
        ),
        patch(
            "app.agent.l1_observe.analysis_node._generate_summary",
            new=AsyncMock(
                return_value=(
                    '{"dimension_key":"land_use","layer":1,'
                    '"word_count":0,"text_summary":""}'
                )
            ),
        ),
        patch(
            "app.services.report_store.ReportStore.get_instance",
            return_value=fake_store,
        ),
        patch(
            "app.services.step_report.save_step_report",
            new=AsyncMock(return_value=None),
        ),
    ):
        from app.agent.l1_observe.analysis_node import analyze_dimension

        state = {
            "dimension_key": "land_use",
            "session_id": "s1",
            "phase": "layer1",
            "config": {"village_name": "田坑村", "village_data": ""},
            "completed_dimensions": {"layer1": [], "layer2": [], "layer3": []},
            "messages": [],
        }
        result = await analyze_dimension(state)

        mock_retrieve.assert_called_once()
        assert "completed_dimensions" in result


def test_analyze_dimension_imports_retrieve_evidence():
    """analyze_dimension should import the new evidence service at module level."""
    import app.agent.l1_observe.analysis_node as mod

    assert hasattr(mod, "retrieve_evidence")
    assert hasattr(mod, "render_evidence_prompt_section")
    assert hasattr(mod, "ExplorationRequest")


def test_optimize_semantics_deleted():
    """_optimize_semantics and _build_explore_brief must be deleted."""
    import app.agent.l1_observe.analysis_node as mod

    assert not hasattr(mod, "_optimize_semantics")
    assert not hasattr(mod, "_build_explore_brief")
