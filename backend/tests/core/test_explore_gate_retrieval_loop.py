import pytest


@pytest.mark.asyncio
async def test_pending_request_routes_scoped_retrieval_and_is_reused(monkeypatch):
    from app.contracts.evidence.evidence_contracts import EvidenceFact, EvidenceSource
    from app.evidence.retrieval import evidence_service as service

    service._EVIDENCE_CACHE.clear()
    service._GATE_EVIDENCE_CACHE.clear()
    calls = []

    async def reports(*args, **kwargs):
        calls.append(("report", kwargs.get("query")))
        return [EvidenceFact(statement="道路服务范围 500 米", source_refs=["report:traffic"])], [
            EvidenceSource(source_type="report", reference="report:traffic")
        ]

    async def empty_kg(*args, **kwargs):
        from app.contracts.evidence.evidence_contracts import SpatialCognitionEvidence

        return [], SpatialCognitionEvidence()

    async def empty_bundle(*args, **kwargs):
        return [], []

    monkeypatch.setattr("app.evidence.retrieval.retrievers.report_retriever.retrieve_from_reports", reports)
    monkeypatch.setattr("app.evidence.retrieval.retrievers.kg_retriever.retrieve_from_kg", empty_kg)
    monkeypatch.setattr("app.evidence.retrieval.retrievers.bundle_retriever.retrieve_from_bundle", empty_bundle)
    monkeypatch.setattr("app.evidence.retrieval.retrievers.artifact_retriever.retrieve_from_artifacts", empty_bundle)
    monkeypatch.setattr("app.evidence.retrieval.retrievers.history_retriever.retrieve_from_history", empty_bundle)

    gate = {
        "feedback_route": "EXPLORE",
        "stage": "L3",
        "pending_requests": [{
            "request_type": "evidence_gap",
            "context": {
                "dimension": "traffic",
                "message": "道路服务范围",
                "required_fact": ["道路服务范围"],
                "entity_scope": ["roads"],
            },
        }],
    }
    results = await service.retrieve_evidence_for_gate(gate, "session-loop")
    assert len(results) == 1
    assert calls == [("report", "道路服务范围")]
    assert service._GATE_EVIDENCE_CACHE["session-loop"]


def test_gate_sync_adapter_is_available():
    from app.evidence.retrieval.evidence_service import retrieve_evidence_for_gate_sync

    assert callable(retrieve_evidence_for_gate_sync)
