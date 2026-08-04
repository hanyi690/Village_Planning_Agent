"""Shared fixtures for L3 PLAN worker tests.

Patches the heavy I/O internals (RAG runtime, ReportStore, SSE,
StatsCollector, step reports, LLM) so the L3 smoke test terminates quickly
and hermetically, without touching the real database, vector store, or
network. Modeled on tests/unit/l2_strategize/conftest.py and
tests/unit/common/test_dimension_runtime.py.
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.modules.schema.contracts.evidence_contracts import (
    EvidenceBundle,
    ExplorationResult,
    SpatialCognitionEvidence,
)


class _FakeLLM:
    async def astream(self, prompt):
        from langchain_core.messages import AIMessage

        yield AIMessage(content="测试输出")
        return


@pytest.fixture
def mock_worker_deps():
    """Patch worker internals; yields fake store / result for assertions."""
    fake_store = MagicMock()
    fake_store.get_latest_version = AsyncMock(return_value=0)

    fake_result = ExplorationResult(
        evidence_bundle=EvidenceBundle(request="x", facts=[], sources=[]),
        spatial_cognition=SpatialCognitionEvidence(village_overview="test"),
    )

    fake_rag = MagicMock()
    fake_rag.generate_queries = AsyncMock(return_value=["村庄用地标准"])
    fake_rag.search = AsyncMock(return_value=[])

    with (
        patch(
            "app.agent.l3_plan.worker.retrieve_evidence",
            new=AsyncMock(return_value=fake_result),
        ),
        patch(
            "app.agent.l3_plan.worker.run_rag",
            new=AsyncMock(return_value=("", None)),
        ),
        patch(
            "app.agent.l3_plan.worker.load_layered_dependency_reports",
            new=AsyncMock(return_value=("L1依赖报告", "L2依赖报告", "同层上下文")),
        ),
        patch(
            "app.agent.l3_plan.worker.publish_dimension_start",
            new=AsyncMock(),
        ),
        patch(
            "app.agent.l3_plan.worker.publish_dimension_delta",
            new=AsyncMock(),
        ),
        patch(
            "app.agent.l3_plan.worker.publish_dimension_complete",
            new=AsyncMock(),
        ),
        patch(
            "app.agent.l3_plan.worker.save_report_immediate",
            new=AsyncMock(),
        ),
        patch(
            "app.agent.l3_plan.worker.generate_summary",
            new=AsyncMock(
                return_value='{"dimension_key":"land_use_planning","layer":3}'
            ),
        ),
        patch(
            "app.agent.l3_plan.worker._get_llm",
            return_value=_FakeLLM(),
        ),
        patch(
            "app.agent.l3_plan.worker.save_step_report",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "app.services.report_store.ReportStore.get_instance",
            return_value=fake_store,
        ),
        patch(
            "app.utils.stats_collector.StatsCollector.get_instance",
            return_value=MagicMock(),
        ),
        patch("app.services.sse.sse_manager.publish", new=AsyncMock()),
        patch(
            "app.services.runtime.PlanningRuntimeService.aget_state_values",
            new=AsyncMock(return_value={}),
        ),
        patch("app.modules.rag.service.RagService.get_instance", return_value=fake_rag),
    ):
        yield {
            "store": fake_store,
            "result": fake_result,
        }
