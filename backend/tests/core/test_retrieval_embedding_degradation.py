import pytest

from app.contracts.evidence.evidence_contracts import (
    EvidenceFact,
    EvidenceSource,
    ExplorationRequest,
    SpatialCognitionEvidence,
)
from app.evidence.retrieval import evidence_service
from app.evidence.retrieval.retrievers import (
    artifact_retriever,
    history_retriever,
    kg_retriever,
    local_text_retriever,
    rag_retriever,
    report_retriever,
)


@pytest.mark.asyncio
async def test_embedding_failure_keeps_non_dense_retrieval_available(monkeypatch) -> None:
    async def local_text(*_args, **_kwargs):
        return [
            EvidenceFact(
                statement="服务半径为 15 分钟",
                source_refs=["local:report:1"],
                source_locator="local:report:1:line-4",
            )
        ], [
            EvidenceSource(
                source_type="local_text",
                reference="local:report:1",
                authority="project_report",
            )
        ]

    async def empty(*_args, **_kwargs):
        return [], []

    async def broken_embedding(*_args, **_kwargs):
        raise RuntimeError("embedding provider unavailable")

    async def empty_kg(*_args, **_kwargs):
        return [], SpatialCognitionEvidence()

    async def versions(*_args, **_kwargs):
        return ()

    monkeypatch.setattr(local_text_retriever, "retrieve_from_local_text", local_text)
    monkeypatch.setattr(report_retriever, "retrieve_from_reports", empty)
    monkeypatch.setattr(artifact_retriever, "retrieve_from_artifacts", empty)
    monkeypatch.setattr(history_retriever, "retrieve_from_history", empty)
    monkeypatch.setattr(kg_retriever, "retrieve_from_kg", empty_kg)
    monkeypatch.setattr(rag_retriever, "retrieve_from_rag", broken_embedding)
    monkeypatch.setattr(
        evidence_service,
        "_active_source_versions",
        versions,
    )
    monkeypatch.setattr(
        "app.infrastructure.context.planning_context_factory.get_cached_context",
        lambda _session_id: None,
    )

    evidence_service._EVIDENCE_CACHE.clear()
    evidence_service._GATE_EVIDENCE_CACHE.clear()
    result = await evidence_service.retrieve_evidence(
        ExplorationRequest(
            run_id="embedding-off-run",
            request_type="fact_check",
            query="服务半径",
            required_facts=["服务半径"],
            context_refs=["source:rag", "source:local_text"],
        ),
        "embedding-off-session",
    )

    assert result.evidence_bundle.facts
    assert result.coverage is not None
    assert result.coverage.sufficient is True
    assert "rag" in result.coverage.source_families_queried
    assert "rag" in result.coverage.unavailable_source_families
    assert any(
        item.get("retriever") == "rag" and item.get("status") == "failed"
        for item in result.coverage.query_trace
    )
