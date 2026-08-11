import pytest


@pytest.mark.asyncio
async def test_retrieve_evidence_caches_same_session_request(monkeypatch):
    from app.agent.explore import service
    from app.modules.schema.contracts.evidence_contracts import ExplorationRequest

    service._EVIDENCE_CACHE.clear()
    calls = {"reports": 0}

    async def reports(*_args, **_kwargs):
        calls["reports"] += 1
        return [], []

    async def empty(*_args, **_kwargs):
        return [], []

    async def empty_kg(*_args, **_kwargs):
        from app.modules.schema.contracts.evidence_contracts import SpatialCognitionEvidence
        return [], SpatialCognitionEvidence()

    monkeypatch.setattr("app.agent.explore.retrievers.report_retriever.retrieve_from_reports", reports)
    monkeypatch.setattr("app.agent.explore.retrievers.instruction_retriever.retrieve_from_instructions", empty)
    monkeypatch.setattr("app.agent.explore.retrievers.kg_retriever.retrieve_from_kg", empty_kg)
    monkeypatch.setattr("app.agent.explore.retrievers.bundle_retriever.retrieve_from_bundle", empty)

    request = ExplorationRequest(
        run_id="r1", request_type="spatial_lookup", query="土地利用",
        stage="L1", dimension_key="land_use", entity_scope=["parcels"],
    )
    first = await service.retrieve_evidence(request, "session-cache-test", "金田村")
    second = await service.retrieve_evidence(request, "session-cache-test", "金田村")
    assert first is second
    assert calls["reports"] == 1
