from __future__ import annotations

from types import SimpleNamespace

import pytest


@pytest.mark.asyncio
async def test_run_rag_is_the_single_unified_evidence_adapter(monkeypatch):
    from app.contracts.evidence.evidence_contracts import (
        EvidenceBundle,
        EvidenceFact,
        EvidenceSource,
        ExplorationResult,
    )
    from app.infrastructure.llm import dimension_runtime

    calls: list[tuple[str, str]] = []

    async def retrieve(request, session_id, village_name="", source_versions=None):
        calls.append((request.dimension_key, session_id))
        return ExplorationResult(
            evidence_bundle=EvidenceBundle(
                request=request.query,
                facts=[EvidenceFact(statement="统一证据")],
                sources=[EvidenceSource(source_type="rag", reference="rag:test")],
            )
        )

    monkeypatch.setattr(
        "app.evidence.retrieval.evidence_service.retrieve_evidence",
        retrieve,
    )
    monkeypatch.setattr(
        "app.evidence.retrieval.retrievers.rag_retriever.consume_rag_log",
        lambda session_id, dimension_key: None,
    )

    context, log = await dimension_runtime.run_rag(
        "traffic",
        SimpleNamespace(name="交通", layer=3),
        {"session_id": "session-adapter", "config": {"village_name": "金田村"}},
    )

    assert calls == [("traffic", "session-adapter")]
    assert "统一证据" in context
    assert log is None


@pytest.mark.asyncio
async def test_legacy_rag_defaults_to_settings_disabled_and_reports_reason(monkeypatch):
    from app.core import settings
    from app.infrastructure.llm.dimension_runtime import retrieve_vector_context

    monkeypatch.setattr(settings, "RAG_ENABLED", False)

    async def state_values(cls, _session_id):
        return {"config": {}}

    monkeypatch.setattr(
        "app.infrastructure.runtime.planning_runtime_service.PlanningRuntimeService.aget_state_values",
        classmethod(state_values),
    )

    context, log = await retrieve_vector_context(
        "traffic",
        SimpleNamespace(layer=3, rag_query="道路专业规范"),
        {"session_id": "session-rag-default-disabled", "config": {}},
    )

    assert context == ""
    assert log is not None
    assert log.rag_enabled is False
    assert log.skip_reason == "disabled_by_config"


@pytest.mark.asyncio
async def test_rag_retriever_does_not_promote_text_without_vector_chunk(monkeypatch):
    from app.evidence.retrieval.retrievers import rag_retriever

    async def legacy(dimension_key, cfg, state):
        return "旧 RAG 片段", SimpleNamespace(retrieval_latency_ms=3, total_results=1)

    monkeypatch.setattr(
        "app.infrastructure.llm.dimension_runtime.retrieve_vector_context",
        legacy,
    )
    async def state_values(cls, session_id):
        return _state_for_adapter(session_id)

    monkeypatch.setattr(
        "app.infrastructure.runtime.planning_runtime_service.PlanningRuntimeService.aget_state_values",
        classmethod(state_values),
    )

    facts, sources = await rag_retriever.retrieve_from_rag(
        "session-rag", "traffic", "L3", query="交通"
    )

    assert facts == []
    assert sources == []
    assert rag_retriever.consume_rag_log("session-rag", "traffic").total_results == 1


def _state_for_adapter(session_id: str) -> dict:
    return {"session_id": session_id, "config": {}}
