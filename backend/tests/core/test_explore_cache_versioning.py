import pytest


@pytest.mark.asyncio
async def test_cache_includes_complete_request_and_source_versions(monkeypatch):
    from app.contracts.evidence.evidence_contracts import ExplorationRequest, SpatialCognitionEvidence
    from app.evidence.retrieval import evidence_service as service

    service._EVIDENCE_CACHE.clear()
    calls = {"reports": 0}

    async def reports(*args, **kwargs):
        calls["reports"] += 1
        return [], []

    async def empty_kg(*args, **kwargs):
        return [], SpatialCognitionEvidence()

    async def empty_bundle(*args, **kwargs):
        return [], []

    monkeypatch.setattr("app.evidence.retrieval.retrievers.report_retriever.retrieve_from_reports", reports)
    monkeypatch.setattr("app.evidence.retrieval.retrievers.kg_retriever.retrieve_from_kg", empty_kg)
    monkeypatch.setattr("app.evidence.retrieval.retrievers.bundle_retriever.retrieve_from_bundle", empty_bundle)

    request = ExplorationRequest(
        run_id="run-cache",
        request_type="spatial_lookup",
        query="土地利用",
        stage="L1",
        dimension_key="land_use",
        entity_scope=["parcels"],
    )
    first = await service.retrieve_evidence(request, "session-version", source_versions={"bundle": "digest-a"})
    same = await service.retrieve_evidence(request, "session-version", source_versions={"bundle": "digest-a"})
    changed_request = await service.retrieve_evidence(
        request.model_copy(update={"questions": ["是否有面积"]}),
        "session-version",
        source_versions={"bundle": "digest-a"},
    )
    changed_source = await service.retrieve_evidence(request, "session-version", source_versions={"bundle": "digest-b"})
    assert first is same
    assert changed_request is not first
    assert changed_source is not first
    assert calls["reports"] == 3
