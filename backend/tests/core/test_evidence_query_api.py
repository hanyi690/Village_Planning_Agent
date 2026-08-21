from types import SimpleNamespace

import pytest

from app.api.v1.contracts import EvidenceQueryRequest
from app.contracts.evidence.evidence_contracts import (
    EvidenceBundle,
    ExplorationResult,
)
from app.contracts.evidence.evidence_packet_contracts import EvidencePacket


def test_public_evidence_query_does_not_preexclude_anchor_classes() -> None:
    request = EvidenceQueryRequest(query="炉池自然村在哪里")

    assert request.entity_scope == []


@pytest.mark.asyncio
async def test_public_evidence_query_returns_unified_packet(monkeypatch) -> None:
    from app.api.v1.routes import evidence as route
    from app.infrastructure.context import planning_context_factory as context_factory
    from app.evidence.retrieval import evidence_service

    context = SimpleNamespace(village_name="金田村", reports={"current_report": "报告"})
    monkeypatch.setattr(
        context_factory,
        "build_planning_context",
        lambda *args, **kwargs: _async_return(context),
    )
    monkeypatch.setattr(context_factory, "get_cached_context", lambda _: context)
    monkeypatch.setattr(
        evidence_service,
        "retrieve_evidence",
        lambda *args, **kwargs: _async_return(
            ExplorationResult(
                evidence_bundle=EvidenceBundle(
                    request="社前村祠堂的BSM",
                    facts=[],
                    sources=[],
                    confidence=0.9,
                ),
                evidence_packet=EvidencePacket(
                    request="社前村祠堂的BSM",
                    sufficiency="partial",
                    query_trace=[{
                        "step": "source_semantic_overlay",
                        "diagnostics": [{
                            "code": "SOURCE_SEMANTIC_INPUT_EMPTY",
                        }],
                    }],
                ),
            )
        ),
    )

    response = await route.query_session_evidence(
        "session-api-evidence",
        EvidenceQueryRequest(query="社前村祠堂的BSM", village_name="金田村"),
    )

    assert response.session_id == "session-api-evidence"
    assert response.evidence_bundle.request == "社前村祠堂的BSM"
    assert response.evidence_packet is not None
    overlay_trace = [
        item
        for item in response.evidence_packet.query_trace
        if item.get("step") == "source_semantic_overlay"
    ]
    assert overlay_trace
    assert any(
        item.get("code") == "SOURCE_SEMANTIC_INPUT_EMPTY"
        for item in overlay_trace[-1].get("diagnostics", [])
    )
    parser_trace = [
        item
        for item in response.evidence_packet.query_trace
        if item.get("step") == "spatial_query_parser"
    ]
    assert parser_trace[-1]["status"] == "disabled"


@pytest.mark.asyncio
async def test_public_evidence_query_exposes_ground_llm_failure(monkeypatch) -> None:
    from app.api.v1.routes import evidence as route
    from app.infrastructure.context import planning_context_factory as context_factory
    from app.evidence.retrieval import evidence_service
    from app.spatial.grounding import flash_mention_extractor

    context = SimpleNamespace(village_name="金田村", reports={"current_report": "报告"})
    monkeypatch.setenv("GROUND_LLM_ENABLED", "true")
    monkeypatch.delenv("DISABLE_GROUND_LLM", raising=False)
    monkeypatch.setattr(
        context_factory,
        "build_planning_context",
        lambda *args, **kwargs: _async_return(context),
    )
    monkeypatch.setattr(context_factory, "get_cached_context", lambda _: context)

    async def fail_parser(*args, **kwargs):
        raise RuntimeError("simulated parser outage")

    monkeypatch.setattr(
        flash_mention_extractor,
        "extract_spatial_reference_spec",
        fail_parser,
    )
    monkeypatch.setattr(
        evidence_service,
        "retrieve_evidence",
        lambda *args, **kwargs: _async_return(
            ExplorationResult(
                evidence_bundle=EvidenceBundle(request="社前村祠堂的BSM"),
                evidence_packet=EvidencePacket(
                    request="社前村祠堂的BSM",
                    sufficiency="partial",
                ),
            )
        ),
    )

    response = await route.query_session_evidence(
        "session-api-ground-failure",
        EvidenceQueryRequest(
            query="社前村祠堂的BSM",
            village_name="金田村",
            request_type="spatial_lookup",
        ),
    )

    parser_trace = [
        item
        for item in response.evidence_packet.query_trace
        if item.get("step") == "spatial_query_parser"
    ]
    assert parser_trace[-1]["status"] == "failed"
    assert "simulated parser outage" in parser_trace[-1]["error"]


async def _async_return(value):
    return value


@pytest.mark.asyncio
async def test_public_evidence_query_explicitly_injects_external_provider(monkeypatch) -> None:
    from app.api.v1.routes import evidence as route
    from app.infrastructure.context import planning_context_factory as context_factory
    from app.evidence.retrieval import evidence_service

    context = SimpleNamespace(village_name="金田村", reports={"current_report": "报告"})
    provider = object()
    policy = object()
    captured = {}
    monkeypatch.setattr(
        context_factory,
        "build_planning_context",
        lambda *args, **kwargs: _async_return(context),
    )
    monkeypatch.setattr(context_factory, "get_cached_context", lambda _: context)
    monkeypatch.setattr(
        "app.application.queries.evidence.get_configured_external_provider",
        lambda categories=None: provider,
    )
    monkeypatch.setattr(
        "app.application.queries.evidence.build_external_evidence_policy",
        lambda dimension, categories=None: policy,
    )

    async def fake_retrieve(*args, **kwargs):
        captured.update(kwargs)
        return ExplorationResult(
            evidence_bundle=EvidenceBundle(
                request="最新人口 external",
                facts=[],
                sources=[],
                confidence=0.0,
            ),
            evidence_packet=EvidencePacket(request="最新人口 external", sufficiency="insufficient"),
        )

    monkeypatch.setattr(evidence_service, "retrieve_evidence", fake_retrieve)
    await route.query_session_evidence(
        "session-api-external",
        EvidenceQueryRequest(
            query="最新人口 external",
            village_name="金田村",
            dimension_key="population",
            include_external=True,
            external_categories=["population"],
        ),
    )

    assert captured["external_port"] is provider
    assert captured["external_policy"] is policy


@pytest.mark.asyncio
async def test_fake_external_provider_is_explicit_and_returns_typed_text_evidence(monkeypatch) -> None:
    from app.application.queries.evidence import get_configured_external_provider
    from app.contracts.workflow.repair import ExternalSearchRequest

    monkeypatch.setenv("EVIDENCE_EXTERNAL_PROVIDER", "fake")
    provider = get_configured_external_provider(["population"])
    assert provider is not None

    result = await provider.search(
        ExternalSearchRequest(
            query_purpose="最新人口",
            allowed_categories=["population"],
            entity_scope=["金田村"],
            search_mode="light",
            result_limit=2,
            content_mode="summary",
            idempotency_key="api-fake-external",
        )
    )

    assert result.retrieval_status == "success"
    assert result.result_records
    assert result.result_records[0]["source"] == "fake-gazetteer"


def test_external_provider_is_disabled_even_when_key_exists(monkeypatch) -> None:
    from app.application.queries.evidence import get_configured_external_provider
    from app.infrastructure.search import UnavailableExternalSearchAdapter

    monkeypatch.setenv("EVIDENCE_EXTERNAL_PROVIDER", "disabled")
    monkeypatch.setenv("EXA_API_KEY", "redacted-test-key")
    provider = get_configured_external_provider()

    assert isinstance(provider, UnavailableExternalSearchAdapter)


@pytest.mark.asyncio
async def test_exa_http_adapter_classifies_auth_failure_without_retry() -> None:
    import httpx

    from app.contracts.workflow.repair import ExternalSearchRequest
    from app.infrastructure.search import ExaHTTPExternalSearchAdapter

    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "unauthorized"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = ExaHTTPExternalSearchAdapter("test-key", client=client)
    result = await adapter.search(
        ExternalSearchRequest(
            query_purpose="测试外源查询",
            search_mode="light",
            result_limit=1,
            content_mode="summary",
            idempotency_key="exa-http-auth-test",
        )
    )
    await adapter.close()

    assert result.retrieval_status == "failed"
    assert result.failure is not None
    assert result.failure.code == "provider_unauthorized"
    assert result.failure.retryable is False


@pytest.mark.asyncio
async def test_exa_http_adapter_maps_highlights_and_closes_injected_transport() -> None:
    import httpx

    from app.contracts.workflow.repair import ExternalSearchRequest
    from app.infrastructure.search import ExaHTTPExternalSearchAdapter

    seen = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["api_key"] = request.headers.get("x-api-key")
        seen["payload"] = request.read().decode("utf-8")
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "title": "县级统计公报",
                        "url": "https://example.test/statistics",
                        "publishedDate": "2026-08-01",
                        "highlights": ["常住人口约 900 人"],
                    }
                ]
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = ExaHTTPExternalSearchAdapter("test-key", client=client)
    result = await adapter.search(
        ExternalSearchRequest(
            query_purpose="金田村 最新人口",
            entity_scope=["金田村"],
            search_mode="light",
            result_limit=5,
            content_mode="summary",
            idempotency_key="exa-http-test",
        )
    )
    await adapter.close()

    assert result.retrieval_status == "success"
    assert result.provider == "exa"
    assert result.result_records[0]["text"] == "常住人口约 900 人"
    assert result.result_records[0]["published_at"] == "2026-08-01"
    assert seen["api_key"] == "test-key"
    assert '"numResults":5' in seen["payload"]
