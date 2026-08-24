"""No-mock retrieval slice for L1 -> KG/bundle -> answer feature identity."""

from types import SimpleNamespace

import pytest

from app.contracts.domain.l1_contracts import L1Fact, L1LocationFact
from app.contracts.evidence.evidence_contracts import ExplorationRequest
from app.contracts.evidence.source_semantic_contracts import (
    SourceFeatureSemanticProposal,
    SourceFeatureSemanticProposalBatch,
)
from app.data.model.canonical import VillageBundle, VillageMetadata
from app.data.model.spatial_types import CurrentAnnotation
from app.evidence.index.place_evidence_index import PlaceEvidenceIndex
from app.evidence.retrieval import evidence_service
from app.evidence.retrieval.evidence_graph import EvidenceGraph
from app.evidence.retrieval.retrievers import bundle_retriever, kg_retriever
from app.infrastructure.kg.builder import KGBuilder


@pytest.mark.asyncio
async def test_real_retrieval_slice_answers_village_facility_bsm(monkeypatch) -> None:
    session_id = "evidence-vertical-slice"
    bundle = VillageBundle(
        village_name="金田村",
        metadata=VillageMetadata(adcode_12="441426110000"),
    )
    bundle.add(
        CurrentAnnotation(
            geometry={"type": "Point", "coordinates": [116.0, 24.0]},
            text="祠堂",
            category="现状设施点",
        )
    )
    kg = KGBuilder.build("金田村", bundle)
    context = SimpleNamespace(
        session_id=session_id,
        village_name="金田村",
        workspace=bundle,
        location_facts=[
            L1LocationFact(
                mention="祠堂",
                normalized_name="祠堂",
                role="facility",
                aliases=["祠堂"],
                spatial_hint="金田村",
                source_span="现状设施 | 祠堂 | 金田村",
                source_report_ref="report:l1:history",
                confidence=0.95,
            )
        ],
        l1_fact_records=[L1Fact(
            fact_id="l1:shrine",
            statement="现状有祠堂",
            fact_kind="document_observation",
            dimension_key="location",
            semantic_type="facility",
            attributes={"normalized_name": "祠堂"},
            value=1,
            unit="处",
            source_refs=["report:l1:history"],
        )],
        kg=kg,
        kg_version=1,
        version=1,
        l1_snapshot_ref="artifact://l1/snapshot",
        data_snapshot=SimpleNamespace(digest=bundle.spatial_snapshot_digest()),
        gazetteer=None,
        current_parcels=lambda: [],
    )
    context.evidence_graph = EvidenceGraph(
        context, index=PlaceEvidenceIndex.build(context)
    )

    async def resolve_bundle(_session_id):
        return bundle

    monkeypatch.setattr(bundle_retriever, "resolve_bundle", resolve_bundle)
    monkeypatch.setattr(kg_retriever, "session_kg", lambda _session_id: kg)
    monkeypatch.setattr(
        "app.infrastructure.context.planning_context_factory.get_cached_context",
        lambda _session_id: context,
    )
    monkeypatch.setattr(
        evidence_service,
        "_active_source_versions",
        lambda _session_id, supplied=None: _versions(),
    )
    evidence_service._EVIDENCE_CACHE.clear()
    evidence_service._GATE_EVIDENCE_CACHE.clear()

    result = await evidence_service.retrieve_evidence(
        ExplorationRequest(
            run_id=session_id,
            request_type="spatial_lookup",
            query="金田村祠堂的BSM",
            stage="L1",
            dimension_key="location",
            entity_scope=["facilities"],
            required_facts=["祠堂的BSM"],
        ),
        session_id,
        village_name="金田村",
    )
    packet = result.evidence_packet

    assert result.coverage is not None
    assert result.coverage.sufficient is True
    assert any(
        item.status == "supported"
        for item in result.coverage.requirement_coverage
    )
    assert any("设施 1 个" in fact.statement for fact in result.evidence_bundle.facts)
    assert any(
        fact.fact_type == "l1_fact" and "祠堂" in fact.statement
        for fact in result.evidence_bundle.facts
    )
    assert any(
        source.reference.startswith("bundle:annotations_current:")
        for source in result.evidence_bundle.sources
    )
    assert [ref.identity.bundle_feature_bsm for ref in packet.candidate_refs] == [
        "44142611000000000001"
    ]
    assert packet.candidate_refs[0].identity.canonical_name == "祠堂"
    assert packet.candidate_refs[0].identity.role == "facility"
    assert packet.sufficiency == "sufficient"
    assert packet.ambiguity_status == "resolved"
    assert packet.candidate_refs[0].geometry_ref == "bundle://feature/44142611000000000001"
    identity_fact = next(
        fact
        for fact in result.evidence_bundle.facts
        if fact.fact_type == "bundle_feature_identity"
    )
    assert identity_fact.fields["bundle_feature_bsm"] == "44142611000000000001"
    assert identity_fact.fields["canonical_name"] == "祠堂"
    assert identity_fact.fields["geometry_authority"] == "bundle"


@pytest.mark.asyncio
async def test_retrieval_slice_uses_simulated_minimax_for_raw_facility_label(monkeypatch) -> None:
    """Raw GIS labels require the typed L1-to-bundle semantic boundary."""
    session_id = "evidence-vertical-semantic-slice"
    bundle = VillageBundle(
        village_name="金田村",
        metadata=VillageMetadata(adcode_12="441426110000"),
    )
    bundle.add(
        CurrentAnnotation(
            geometry={"type": "Point", "coordinates": [116.0, 24.0]},
            text="祠",
            category="现状设施点",
            _raw={"source_feature_id": "feature:vertical:shrine"},
        )
    )
    kg = KGBuilder.build("金田村", bundle)
    feature_id = "feature:vertical:shrine"
    proposal_batch = SourceFeatureSemanticProposalBatch(
        proposals=[SourceFeatureSemanticProposal(
            source_feature_id=feature_id,
            candidate_ref="l1:l1:shrine:entity",
            supporting_fact_refs=["l1:shrine"],
        )]
    )

    class _Structured:
        async def ainvoke(self, _messages):
            return proposal_batch

    class _SimulatedMinimax:
        calls = 0

        def with_structured_output(self, _response_model, **_kwargs):
            self.calls += 1
            return _Structured()

    from app.evidence.identity.flash_source_semantic_classifier import (
        SourceSemanticClassifier,
    )
    from app.evidence.retrieval import evidence_service

    simulated = _SimulatedMinimax()
    monkeypatch.setattr("app.core.settings.SOURCE_SEMANTIC_LLM_ENABLED", True)
    monkeypatch.setattr(
        "app.evidence.identity.flash_source_semantic_classifier.create_minimax_source_semantic_classifier",
        lambda: SourceSemanticClassifier(llm=simulated),
    )
    context = SimpleNamespace(
        session_id=session_id,
        village_name="金田村",
        workspace=bundle,
        location_facts=[L1LocationFact(
            mention="祠堂",
            normalized_name="祠堂",
            role="facility",
            aliases=["祠堂", "祠"],
            spatial_hint="金田村",
            source_span="现状设施 | 祠堂 | 金田村",
            source_report_ref="report:l1:history",
            confidence=0.95,
        )],
        l1_fact_records=[L1Fact(
            fact_id="l1:shrine",
            statement="现状有祠堂",
            fact_kind="document_observation",
            semantic_type="facility",
            attributes={"normalized_name": "祠堂"},
            value=1,
            unit="处",
            source_refs=["report:l1:history"],
        )],
        kg=kg,
        kg_version=1,
        version=1,
        l1_snapshot_ref="artifact://l1/semantic-snapshot",
        data_snapshot=SimpleNamespace(digest=bundle.spatial_snapshot_digest()),
        gazetteer=None,
        current_parcels=lambda: [],
        source_semantic_decisions={},
        source_semantic_fingerprint="",
        source_semantic_diagnostics=[],
        evidence_graph_key="graph:vertical-semantic",
    )

    async def resolve_bundle(_session_id):
        return bundle

    monkeypatch.setattr(bundle_retriever, "resolve_bundle", resolve_bundle)
    monkeypatch.setattr(kg_retriever, "session_kg", lambda _session_id: kg)
    monkeypatch.setattr(
        "app.infrastructure.context.planning_context_factory.get_cached_context",
        lambda _session_id: context,
    )
    monkeypatch.setattr(
        evidence_service,
        "_active_source_versions",
        lambda _session_id, supplied=None: _versions(),
    )
    evidence_service._EVIDENCE_CACHE.clear()
    evidence_service._GATE_EVIDENCE_CACHE.clear()

    result = await evidence_service.retrieve_evidence(
        ExplorationRequest(
            run_id=session_id,
            request_type="spatial_lookup",
            query="金田村祠堂的BSM",
            stage="L1",
            dimension_key="location",
            entity_scope=["facilities"],
            required_facts=["祠堂的BSM"],
        ),
        session_id,
        village_name="金田村",
    )

    packet = result.evidence_packet
    assert result.coverage is not None
    assert result.coverage.sufficient is True
    assert simulated.calls == 2
    assert packet.candidate_refs
    assert packet.candidate_refs[0].identity.canonical_name == "祠堂"
    assert packet.candidate_refs[0].identity.bundle_feature_bsm == (
        "44142611000000000001"
    )
    assert packet.candidate_refs[0].geometry_ref == (
        "bundle://feature/44142611000000000001"
    )
    assert packet.ambiguity_status == "resolved"
    assert "l1:shrine" in packet.candidate_refs[0].l1_fact_refs
    assert any(
        item.get("step") == "source_semantic_runtime"
        and item.get("status") == "snapshot_ready"
        for item in packet.query_trace
    )
    assert any(
        item.get("step") == "source_semantic_overlay"
        and item.get("decision_count") == 1
        for item in packet.query_trace
    )


async def _versions():
    return (("test", "1"),)
