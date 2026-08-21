from types import SimpleNamespace

import pytest


def _report_bundle():
    return SimpleNamespace(
        documents=SimpleNamespace(report_refs=[{
            "layer": 2,
            "dimension_key": "public_service",
            "report_id": "report-semantic-1",
            "version": 1,
            "summary": "",
        }])
    )


async def _async_report_bundle():
    return _report_bundle()


@pytest.mark.asyncio
async def test_local_text_retriever_returns_planning_span_without_vector_service(monkeypatch):
    from app.evidence.retrieval.retrievers.local_text_retriever import (
        retrieve_from_local_text,
    )

    context = SimpleNamespace(
        input_documents=[{
            "source": "task_description",
            "name": "任务描述",
            "content": "公共服务设施应结合村民日常出行和服务半径统筹布局，优先补足村域北部短板。",
        }],
        location_facts=[],
        l1_snapshot_ref="l1:test",
    )
    monkeypatch.setattr(
        "app.infrastructure.context.planning_context_factory.get_cached_context",
        lambda session_id: context,
    )

    facts, sources = await retrieve_from_local_text(
        "session-local-text",
        "public_service",
        "L2",
        query="公共服务布局",
        required_facts=["服务半径"],
        entity_scope=["facilities"],
    )

    assert facts
    assert facts[0].fact_type == "planning_text"
    assert facts[0].fields["evidence_role"] == "planning_background"
    assert facts[0].fields["source_kind"] == "bundle_document"
    assert "服务半径" in facts[0].evidence_span
    assert sources[0].source_type == "bundle"
    assert "local-text:bundle_document:" in sources[0].reference


@pytest.mark.asyncio
async def test_rag_unavailable_does_not_fallback_to_session_text(monkeypatch):
    from app.evidence.retrieval.retrievers import rag_retriever

    async def legacy(dimension_key, cfg, state):
        return "", SimpleNamespace(
            retrieved_chunks=[],
            skip_reason="vector store unavailable; skipped query generation",
            total_results=0,
        )

    async def state_values(cls, session_id):
        return {"session_id": session_id, "config": {}}

    monkeypatch.setattr(
        "app.infrastructure.llm.dimension_runtime.retrieve_vector_context",
        legacy,
    )
    monkeypatch.setattr(
        "app.infrastructure.runtime.planning_runtime_service.PlanningRuntimeService.aget_state_values",
        classmethod(state_values),
    )

    facts, sources = await rag_retriever.retrieve_from_rag(
        "session-rag-unavailable",
        "traffic",
        "L3",
        query="交通组织",
    )

    assert facts == []
    assert sources == []
    assert rag_retriever.peek_rag_log(
        "session-rag-unavailable", "traffic"
    ).skip_reason.startswith("vector store unavailable")


@pytest.mark.asyncio
async def test_report_retriever_keeps_semantic_planning_sentence_without_digits(monkeypatch):
    from app.evidence.retrieval.retrievers import report_retriever

    class FakeStore:
        async def get_reports_by_ids(self, report_ids):
            return {
                "report-semantic-1": SimpleNamespace(
                    content="公共服务设施应结合村民日常需求统筹布局，优先完善北部服务短板。"
                )
            }

    monkeypatch.setattr(report_retriever.ReportStore, "get_instance", lambda: FakeStore())
    monkeypatch.setattr(
        report_retriever,
        "resolve_bundle",
        lambda session_id: _async_report_bundle(),
    )
    facts, sources = await report_retriever.retrieve_from_reports(
        "session-report",
        "public_service",
        "L2",
        query="公共服务布局",
    )

    assert facts
    assert facts[0].fact_type == "planning_text"
    assert facts[0].fields["evidence_role"] == "planning_background"
    assert "优先完善" in facts[0].statement
    assert sources[0].reference == "L2:public_service:report-semantic-1"


@pytest.mark.asyncio
async def test_report_prose_never_becomes_spatial_grounding_fact(monkeypatch):
    from app.evidence.retrieval.retrievers import report_retriever

    class FakeStore:
        async def get_reports_by_ids(self, report_ids):
            return {
                "report-spatial-wording-1": SimpleNamespace(
                    content="北部公共服务设施位于村域北侧，占地 2.4 公顷，规划建设综合服务中心。"
                )
            }

    monkeypatch.setattr(report_retriever.ReportStore, "get_instance", lambda: FakeStore())
    bundle = _report_bundle()
    bundle.documents.report_refs[0]["report_id"] = "report-spatial-wording-1"

    async def bundle_for_session(session_id):
        return bundle

    monkeypatch.setattr(report_retriever, "resolve_bundle", bundle_for_session)

    facts, _sources = await report_retriever.retrieve_from_reports(
        "session-report-spatial-wording",
        "public_service",
        "L2",
        query="公共服务设施建设",
    )

    assert facts
    assert all(fact.evidence_role == "planning_background" for fact in facts)
    assert all(fact.spatial_granularity == "none" for fact in facts)
    assert all(fact.planning_use == "context" for fact in facts)


def test_context_injection_routes_local_text_but_not_implicit_rag():
    from app.contracts.evidence.evidence_contracts import ExplorationRequest
    from app.evidence.retrieval.router import RetrieverKind, route_request

    plan = route_request(ExplorationRequest(
        run_id="run-local-text",
        request_type="spatial_lookup",
        query="公共服务布局",
        query_purpose="context_injection",
        dimension_key="public_service",
        entity_scope=["facilities"],
    ))

    assert RetrieverKind.LOCAL_TEXT in plan
    assert RetrieverKind.RAG not in plan


def test_explicit_rag_is_a_separate_external_source():
    from app.contracts.evidence.evidence_contracts import ExplorationRequest
    from app.evidence.retrieval.router import RetrieverKind, route_request

    plan = route_request(ExplorationRequest(
        run_id="run-rag",
        request_type="spatial_lookup",
        query="公共服务技术标准",
        query_purpose="professional_reference",
        context_refs=["source:rag"],
    ))

    assert RetrieverKind.RAG in plan
    assert RetrieverKind.HISTORY not in plan


def test_evidence_prompt_separates_report_background_from_spatial_binding():
    from app.contracts.evidence.evidence_contracts import (
        EvidenceBundle,
        EvidenceFact,
        SpatialCognitionEvidence,
    )
    from app.evidence.retrieval.evidence_service import render_evidence_prompt_section

    prompt = render_evidence_prompt_section(
        EvidenceBundle(
            request="社前村祠堂的规划背景",
            facts=[
                EvidenceFact(
                    statement="公共服务设施应优先完善北部服务短板。",
                    source_refs=["L2:public_service:report-1"],
                    fact_type="planning_text",
                    evidence_role="planning_background",
                    source_kind="analysis_report",
                    spatial_granularity="none",
                    planning_use="context",
                ),
                EvidenceFact(
                    statement="祠堂的 bundle feature BSM 为 892。",
                    source_refs=["bundle:annotations_current:892"],
                    spatial_refs=["bundle://feature/892"],
                    fact_type="bundle_feature_identity",
                    evidence_role="location_binding",
                    source_kind="bundle_feature",
                    spatial_granularity="feature",
                    planning_use="grounding",
                ),
            ],
        ),
        SpatialCognitionEvidence(kg_confidence=0.9),
    )

    assert "规划语义背景（仅辅助决策，不产生空间位置）" in prompt
    assert "空间事实与定位依据" in prompt
    assert "report-1" in prompt
    assert "bundle://feature/892" in prompt


@pytest.mark.asyncio
async def test_unified_retrieval_consumes_authoritative_l1_fact_records(monkeypatch):
    from app.contracts.domain.l1_contracts import L1Fact
    from app.contracts.evidence.evidence_contracts import ExplorationRequest
    from app.evidence.retrieval import evidence_service
    from app.contracts.evidence.evidence_contracts import SpatialCognitionEvidence

    context = SimpleNamespace(
        l1_snapshot_ref="l1:snapshot:typed",
        l1_fact_records=[
            L1Fact(
                fact_id="l1:fact:typed-hall",
                statement="L1空间事实：祠堂（角色=facility），空间提示=社前村",
                confidence=0.96,
                fact_kind="document_observation",
                dimension_key="socio_economic",
                subject_scope="祠堂",
                semantic_type="facility",
                attributes={"normalized_name": "祠堂", "role": "facility"},
                source_refs=["report:current#socio_economic"],
                source_span="社前村现状设施包括祠堂",
            )
        ],
        location_facts=[],
    )

    async def empty_reports(*_args, **_kwargs):
        return [], []

    async def empty_kg(*_args, **_kwargs):
        return [], SpatialCognitionEvidence()

    async def empty_bundle(*_args, **_kwargs):
        return [], []

    monkeypatch.setattr(
        "app.infrastructure.context.planning_context_factory.get_cached_context",
        lambda _session_id: context,
    )
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
    evidence_service._EVIDENCE_CACHE.clear()

    result = await evidence_service.retrieve_evidence(
        ExplorationRequest(
            run_id="run-typed-l1",
            request_type="spatial_lookup",
            query="社前村祠堂",
            stage="L2",
            dimension_key="socio_economic",
            entity_scope=["facilities"],
        ),
        "session-typed-l1",
        village_name="金田村",
    )

    typed = [
        fact
        for fact in result.evidence_bundle.facts
        if fact.fact_type == "l1_fact"
    ]
    assert len(typed) == 1
    assert typed[0].fields["fact_id"] == "l1:fact:typed-hall"
    assert typed[0].support_relation == "l1_typed_fact"
    assert typed[0].evidence_role == "location_binding"
    assert typed[0].spatial_granularity == "feature"
    assert typed[0].planning_use == "grounding"


@pytest.mark.asyncio
async def test_packet_trace_marks_rag_unavailable_without_local_source_relabeling(monkeypatch):
    from types import SimpleNamespace

    from app.contracts.evidence.evidence_contracts import ExplorationRequest, SpatialCognitionEvidence
    from app.evidence.retrieval import evidence_service as service

    service._EVIDENCE_CACHE.clear()

    async def empty_reports(*_args, **_kwargs):
        return [], []

    async def empty_kg(*_args, **_kwargs):
        return [], SpatialCognitionEvidence()

    async def empty_bundle(*_args, **_kwargs):
        return [], []

    async def empty_rag(*_args, **_kwargs):
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
    monkeypatch.setattr(
        "app.evidence.retrieval.retrievers.rag_retriever.retrieve_from_rag",
        empty_rag,
    )
    monkeypatch.setattr(
        "app.evidence.retrieval.retrievers.rag_retriever.peek_rag_log",
        lambda *_args: SimpleNamespace(skip_reason="vector store unavailable"),
    )
    monkeypatch.setattr(
        "app.infrastructure.context.planning_context_factory.get_cached_context",
        lambda _session_id: None,
    )

    result = await service.retrieve_evidence(
        ExplorationRequest(
            run_id="run-rag-unavailable",
            request_type="spatial_lookup",
            query="专业设施配置标准",
            query_purpose="professional_reference",
            context_refs=["source:rag"],
        ),
        "session-rag-trace",
    )

    assert result.evidence_packet is not None
    assert any(
        trace.get("status") == "external_rag_unavailable"
        for trace in result.evidence_packet.query_trace
        if isinstance(trace, dict)
    )
    assert all(source.source_type != "rag" for source in result.evidence_bundle.sources)


def test_prompt_separates_report_background_from_l1_spatial_evidence():
    from app.contracts.evidence.evidence_contracts import EvidenceBundle, EvidenceFact
    from app.contracts.evidence.evidence_packet_contracts import EvidencePacket
    from app.contracts.evidence.feature_identity_contracts import (
        BundleFeatureIdentity,
        FeatureEvidenceRef,
    )
    from app.evidence.retrieval.evidence_service import render_evidence_prompt_section

    report_fact = EvidenceFact(
        statement="报告分析：公共文化设施应结合服务半径和村民日常出行统筹布局。",
        confidence=0.9,
        source_refs=["report:architecture"],
        fact_type="planning_text",
        evidence_role="planning_background",
        source_kind="report",
        spatial_granularity="none",
        planning_use="context",
    )
    l1_fact = EvidenceFact(
        statement="L1空间事实：祠堂，空间提示=社前村。",
        confidence=0.95,
        source_refs=["l1:fact:hall"],
        fact_type="l1_fact",
        evidence_role="location_binding",
        source_kind="l1_typed_fact",
        spatial_granularity="feature",
        planning_use="grounding",
    )
    feature = FeatureEvidenceRef(
        identity=BundleFeatureIdentity(
            bundle_feature_bsm="44142621100000000001",
            canonical_name="祠堂",
            role="facility",
            aliases=["社前祠堂"],
            source_layer="facilities_current",
            source_bsm="44142621100000000001",
        ),
        geometry_ref="bundle://feature/44142621100000000001",
        geometry_authority="bundle",
        related_parcel_bsms=["44142621100000000002"],
        relation_refs=["http://village-planning.org/ontology#nearby"],
        l1_fact_refs=["l1:fact:hall"],
        provenance_refs=["bundle:facilities_current"],
        source_authority_score=1.0,
        semantic_match_score=0.72,
        spatial_support_score=0.72,
        retrieval_score=0.72,
    )

    prompt = render_evidence_prompt_section(
        EvidenceBundle(
            request="社前村祠堂",
            facts=[report_fact, l1_fact],
        ),
        packet=EvidencePacket(
            request="社前村祠堂",
            candidate_refs=[feature],
            ambiguity_status="resolved",
            sufficiency="sufficient",
            query_trace=[
                {
                    "step": "source_semantic_runtime",
                    "status": "unresolved_or_disabled",
                    "diagnostics": [
                        {"code": "SOURCE_SEMANTIC_LLM_DISABLED"}
                    ],
                },
                {
                    "step": "candidate_generation_status",
                    "statuses": ["unresolved"],
                    "reasons": ["no candidate carries the requested village scope"],
                },
            ],
        ),
    )

    assert "规划语义背景（仅辅助决策，不产生空间位置）" in prompt
    assert report_fact.statement in prompt
    assert "空间事实与定位依据" in prompt
    assert l1_fact.statement in prompt
    assert "geometry_authority=bundle" in prompt
    assert "aliases=社前祠堂" in prompt
    assert "source_layer=facilities_current" in prompt
    assert "related_parcels=44142621100000000002" in prompt
    assert "KG_relations=nearby" in prompt
    assert "L1_facts=l1:fact:hall" in prompt
    assert "ambiguity=resolved" in prompt
    assert "typed L1 spatial fact" in prompt
    assert "SOURCE_SEMANTIC_LLM_DISABLED" in prompt
    assert "候选生成诊断（不等于候选为空）" in prompt
    assert "no candidate carries the requested village scope" in prompt
    assert "POINT(" not in prompt


@pytest.mark.asyncio
async def test_structured_query_scopes_augment_unscoped_retrieval(monkeypatch):
    from app.contracts.evidence.evidence_contracts import ExplorationRequest
    from app.contracts.spatial.spatial_reference_contracts import SpatialReferenceSpec
    from app.evidence.retrieval import evidence_service as service
    from app.evidence.retrieval.query_planner import EvidenceQueryPlan
    from app.infrastructure.context import planning_context_factory

    captured_requests = []

    def capture_plan(request):
        captured_requests.append(request)
        return EvidenceQueryPlan(
            request_fingerprint="structured-scope-test",
            queries=(),
        )

    async def source_versions(*_args, **_kwargs):
        return ()

    service._EVIDENCE_CACHE.clear()
    monkeypatch.setattr(service, "build_query_plan", capture_plan)
    monkeypatch.setattr(service, "_active_source_versions", source_versions)
    monkeypatch.setattr(planning_context_factory, "get_cached_context", lambda _session_id: None)

    result = await service.retrieve_evidence(
        ExplorationRequest(
            run_id="run-structured-scope",
            request_type="spatial_lookup",
            query="炉池自然村附近可建设地块",
            entity_scope=[],
        ),
        "session-structured-scope",
        village_name="金田村",
        spatial_spec=SpatialReferenceSpec(
            type="attributive",
            semantic_terms=["炉池自然村", "地块"],
            retrieval_scopes=["hazards", "parcels"],
        ),
    )

    assert captured_requests[0].entity_scope == ["hazards", "parcels"]
    trace = next(
        item
        for item in result.evidence_packet.query_trace
        if item.get("step") == "semantic_candidate_scope"
    )
    assert trace["status"] == "llm_structured"
    assert trace["effective_scopes"] == ["hazards", "parcels"]
