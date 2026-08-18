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
async def test_rag_retriever_adapts_legacy_vector_result(monkeypatch):
    from app.evidence.retrieval.retrievers import rag_retriever

    async def legacy(dimension_key, cfg, state):
        return "旧 RAG 片段", SimpleNamespace(retrieval_latency_ms=3, total_results=1)

    monkeypatch.setattr(
        "app.infrastructure.llm.dimension_runtime._legacy_run_rag",
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

    assert [fact.statement for fact in facts] == ["旧 RAG 片段"]
    assert sources[0].reference == "rag:session-rag:traffic"
    assert rag_retriever.consume_rag_log("session-rag", "traffic").total_results == 1


def _state_for_adapter(session_id: str) -> dict:
    return {"session_id": session_id, "config": {}}
