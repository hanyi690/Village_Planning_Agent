import pytest


class _SimulatedExternalProvider:
    version = "sim-external-v1"

    def __init__(self, records):
        self.records = records
        self.calls = 0

    async def search(self, request):
        from app.contracts.workflow.repair import ExternalSearchResult

        self.calls += 1
        return ExternalSearchResult(
            provider="simulated-external",
            request_id=request.idempotency_key,
            resolved_search_mode=request.search_mode,
            result_records=self.records,
            retrieval_status="success",
        )


@pytest.mark.asyncio
async def test_external_fallback_runs_only_after_local_sufficiency_gap(monkeypatch):
    from app.contracts.evidence.evidence_contracts import ExplorationRequest, SpatialCognitionEvidence
    from app.evidence.retrieval import evidence_service as service
    from app.evidence.retrieval.external_search_policy import ExternalSearchPolicy

    service._EVIDENCE_CACHE.clear()

    async def empty_reports(*_args, **_kwargs):
        return [], []

    async def empty_kg(*_args, **_kwargs):
        return [], SpatialCognitionEvidence()

    async def empty_bundle(*_args, **_kwargs):
        return [], []

    monkeypatch.setattr(
        "app.evidence.retrieval.retrievers.report_retriever.retrieve_from_reports",
        empty_reports,
    )
    monkeypatch.setattr(
        "app.evidence.retrieval.retrievers.kg_retriever.retrieve_from_kg",
        empty_kg,
    )
    monkeypatch.setattr(
        "app.evidence.retrieval.retrievers.bundle_retriever.retrieve_from_bundle",
        empty_bundle,
    )

    provider = _SimulatedExternalProvider(
        [{"text": "县级规划政策摘要", "source": "sim-source", "confidence": 0.8}]
    )
    request = ExplorationRequest(
        run_id="external-fallback",
        request_type="evidence_gap",
        query="最新政策 external",
        stage="L1",
        dimension_key="location",
        required_facts=["县级规划政策"],
    )

    result = await service.retrieve_evidence(
        request,
        "session-external-fallback",
        external_port=provider,
        external_policy=ExternalSearchPolicy(allowed_dimensions=["location"]),
    )

    assert provider.calls == 1
    assert result.evidence_bundle.sources[0].source_type == "external"
    assert result.evidence_bundle.facts[0].status == "needs_review"
    assert result.evidence_bundle.facts[0].evidence_role == "external_context"
    assert result.evidence_bundle.facts[0].source_kind == "external_search"
    assert result.evidence_bundle.facts[0].spatial_granularity == "none"
    assert result.evidence_bundle.facts[0].planning_use == "context"
    assert result.evidence_packet is not None
    assert result.evidence_packet.external_refs
    assert result.evidence_packet.candidate_refs == []
    assert any(
        trace.get("step") == "external_policy"
        for trace in result.evidence_packet.query_trace
        if isinstance(trace, dict)
    )


@pytest.mark.asyncio
async def test_external_provider_is_not_called_when_local_evidence_is_sufficient(monkeypatch):
    from app.contracts.evidence.evidence_contracts import (
        EvidenceFact,
        EvidenceSource,
        ExplorationRequest,
        SpatialCognitionEvidence,
    )
    from app.evidence.retrieval import evidence_service as service
    from app.evidence.retrieval.external_search_policy import ExternalSearchPolicy

    service._EVIDENCE_CACHE.clear()

    async def local_reports(*_args, **_kwargs):
        return [
            EvidenceFact(
                statement="现状道路已经完成调查",
                confidence=0.95,
                source_refs=["report:l1"],
            )
        ], [EvidenceSource(source_type="report", reference="report:l1")]

    async def empty_kg(*_args, **_kwargs):
        return [], SpatialCognitionEvidence()

    async def empty_bundle(*_args, **_kwargs):
        return [], []

    monkeypatch.setattr(
        "app.evidence.retrieval.retrievers.report_retriever.retrieve_from_reports",
        local_reports,
    )
    monkeypatch.setattr(
        "app.evidence.retrieval.retrievers.kg_retriever.retrieve_from_kg",
        empty_kg,
    )
    monkeypatch.setattr(
        "app.evidence.retrieval.retrievers.bundle_retriever.retrieve_from_bundle",
        empty_bundle,
    )

    provider = _SimulatedExternalProvider([])
    request = ExplorationRequest(
        run_id="external-not-needed",
        request_type="fact_check",
        query="道路调查",
        stage="L1",
        dimension_key="traffic",
        required_facts=[],
    )
    result = await service.retrieve_evidence(
        request,
        "session-external-not-needed",
        external_port=provider,
        external_policy=ExternalSearchPolicy(allowed_dimensions=["traffic"]),
    )

    assert provider.calls == 0
    assert result.evidence_packet is not None
    assert result.evidence_packet.external_refs == []


@pytest.mark.asyncio
async def test_local_evidence_graph_resolves_facility_bsm_before_external_fallback(monkeypatch):
    from types import SimpleNamespace

    from app.contracts.evidence.evidence_contracts import ExplorationRequest
    from app.contracts.evidence.evidence_packet_contracts import EvidencePacket
    from app.contracts.evidence.feature_identity_contracts import (
        BundleFeatureIdentity,
        FeatureEvidenceRef,
    )
    from app.evidence.retrieval import evidence_service as service
    from app.evidence.retrieval.external_search_policy import ExternalSearchPolicy

    service._EVIDENCE_CACHE.clear()

    async def empty_retriever(*_args, **_kwargs):
        return [], []

    async def empty_kg(*_args, **_kwargs):
        from app.contracts.evidence.evidence_contracts import SpatialCognitionEvidence

        return [], SpatialCognitionEvidence()

    def empty_l1(*_args, **_kwargs):
        return [], []

    monkeypatch.setattr(
        "app.evidence.retrieval.retrievers.report_retriever.retrieve_from_reports",
        empty_retriever,
    )
    monkeypatch.setattr(
        "app.evidence.retrieval.retrievers.bundle_retriever.retrieve_from_bundle",
        empty_retriever,
    )
    monkeypatch.setattr(
        "app.evidence.retrieval.retrievers.kg_retriever.retrieve_from_kg",
        empty_kg,
    )
    monkeypatch.setattr(
        "app.evidence.retrieval.retrievers.l1_retriever.retrieve_from_l1_context",
        empty_l1,
    )

    context = SimpleNamespace(
        village_name="社前村",
        data_snapshot=SimpleNamespace(digest="bundle-digest-facility"),
        evidence_graph=object(),
    )
    packet = EvidencePacket(
        request="社前村祠堂的BSM",
        candidate_refs=[
            FeatureEvidenceRef(
                identity=BundleFeatureIdentity(
                    bundle_feature_bsm="44142611000000000001",
                    source_feature_id="facility-001",
                    source_layer="facilities_current",
                    bsm_kind="source",
                    bundle_snapshot_digest="bundle-digest-facility",
                ),
                entity_refs=["kg:facility:001"],
                geometry_ref="bundle://facilities_current/facility-001",
                source_authority_score=1.0,
                semantic_match_score=0.96,
                spatial_support_score=0.96,
                retrieval_score=0.96,
            )
        ],
    )

    monkeypatch.setattr(
        "app.infrastructure.context.planning_context_factory.get_cached_context",
        lambda _session_id: context,
    )
    monkeypatch.setattr(
        "app.evidence.retrieval.evidence_graph.enrich_evidence_packet_with_spatial_graph",
        lambda current_packet, *_args, **_kwargs: packet,
    )

    provider = _SimulatedExternalProvider([])
    request = ExplorationRequest(
        run_id="facility-bsm-local-graph",
        request_type="spatial_lookup",
        query="社前村祠堂的BSM",
        stage="L1",
        dimension_key="location",
        required_facts=["祠堂的BSM"],
        entity_scope=["facilities"],
    )

    result = await service.retrieve_evidence(
        request,
        "session-facility-bsm-local-graph",
        village_name="社前村",
        external_port=provider,
        external_policy=ExternalSearchPolicy(allowed_dimensions=["location"]),
    )

    assert provider.calls == 0
    assert result.evidence_packet is not None
    assert result.evidence_packet.candidate_refs[0].identity.bundle_feature_bsm == (
        "44142611000000000001"
    )
    assert result.evidence_bundle.unresolved == []
    assert any(
        fact.fact_type == "bundle_feature_identity"
        and fact.feature_bsm == "44142611000000000001"
        for fact in result.evidence_bundle.facts
    )
