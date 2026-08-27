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
        SpatialCognitionEvidence,
    )
    from app.infrastructure.llm import dimension_runtime

    calls: list[tuple[str, str]] = []

    async def retrieve(request, session_id, village_name="", source_versions=None):
        assert request.project_cognition_digest.startswith("sha256:")
        assert request.project_scope["village_name"] == "金田村"
        calls.append((request.dimension_key, session_id))
        return ExplorationResult(
            evidence_bundle=EvidenceBundle(
                request=request.query,
                facts=[EvidenceFact(statement="统一证据")],
                sources=[EvidenceSource(source_type="rag", reference="rag:test")],
            ),
            spatial_cognition=SpatialCognitionEvidence(kg_confidence=0.8),
        )

    monkeypatch.setattr(
        "app.evidence.retrieval.evidence_service.retrieve_evidence",
        retrieve,
    )
    monkeypatch.setattr(
        "app.infrastructure.context.planning_context_factory.get_cached_context",
        lambda _session_id: SimpleNamespace(
            session_id="session-adapter",
            village_name="金田村",
            data_snapshot=SimpleNamespace(digest="bundle-digest"),
            l1_fact_records=[],
            reports={},
        ),
    )
    monkeypatch.setattr(
        "app.evidence.retrieval.retrievers.rag_retriever.consume_rag_log",
        lambda session_id, dimension_key: None,
    )

    trace: dict[str, object] = {}
    context, log = await dimension_runtime.run_rag(
        "traffic",
        SimpleNamespace(name="交通", layer=3),
        {"session_id": "session-adapter", "config": {"village_name": "金田村"}},
        trace_sink=trace,
    )

    assert calls == [("traffic", "session-adapter")]
    assert "统一证据" in context
    assert log is None
    assert trace["source_types"] == ["rag"]
    assert trace["fact_count"] == 1
    assert trace["kg_confidence"] == 0.8
    assert trace["project_cognition_digest"].startswith("sha256:")
    assert trace["project_scope"]["village_name"] == "金田村"


@pytest.mark.asyncio
async def test_l1_followup_reuses_router_and_keeps_evidence_locators(monkeypatch):
    from app.contracts.evidence.evidence_contracts import (
        EvidenceBundle,
        EvidenceFact,
        EvidenceSource,
        ExplorationResult,
    )
    from app.infrastructure.llm import dimension_runtime

    async def retrieve(request, session_id, village_name="", source_versions=None):
        assert request.request_type == "fact_check"
        assert request.context_refs == []
        assert request.project_cognition_digest.startswith("sha256:")
        assert request.project_scope["village_name"] == "金田村"
        return ExplorationResult(
            evidence_bundle=EvidenceBundle(
                request=request.query,
                facts=[EvidenceFact(
                    statement="村道位于东侧",
                    source_refs=["local:report:1"],
                    spatial_refs=["feature:road-1"],
                    evidence_span="【交通现状】第 4 行",
                    source_locator="input:village_data:line-4",
                )],
                sources=[EvidenceSource(
                    source_type="local_text",
                    reference="local:report:1",
                    snapshot_ref="snapshot:l1:1",
                )],
            )
        )

    monkeypatch.setattr(
        "app.evidence.retrieval.evidence_service.retrieve_evidence",
        retrieve,
    )
    monkeypatch.setattr(
        "app.infrastructure.context.planning_context_factory.get_cached_context",
        lambda _session_id: SimpleNamespace(
            session_id="session-followup",
            village_name="金田村",
            data_snapshot=SimpleNamespace(digest="bundle-digest"),
            l1_fact_records=[],
            reports={},
        ),
    )

    context, trace = await dimension_runtime.run_targeted_evidence(
        "traffic",
        type("Cfg", (), {"layer": 1})(),
        {"session_id": "session-followup", "config": {"village_name": "金田村"}},
        query="确认村道",
        required_facts=["村道"],
    )

    assert "村道位于东侧" in context
    evidence_trace = next(item for item in trace if item.get("step") == "l1_followup_evidence")
    assert evidence_trace["facts"][0]["source_locator"] == "input:village_data:line-4"
    assert evidence_trace["facts"][0]["spatial_refs"] == ["feature:road-1"]


def test_analysis_projection_does_not_include_retrieval_trace_or_raw_body():
    from app.contracts.evidence.evidence_contracts import (
        EvidenceBundle,
        EvidenceFact,
        ExplorationResult,
    )
    from app.contracts.evidence.evidence_packet_contracts import EvidencePacket
    from app.infrastructure.llm import dimension_runtime

    result = ExplorationResult(
        evidence_bundle=EvidenceBundle(
            request="道路",
            facts=[EvidenceFact(statement="村道位于东侧")],
        ),
        evidence_packet=EvidencePacket(
            request="道路",
            query_trace=[{"sql": "SECRET SQL", "raw_rows": ["SECRET ROW"]}],
            missing_evidence=["道路等级"],
        ),
    )

    context = dimension_runtime._analysis_evidence_context(result)

    assert "村道位于东侧" in context
    assert "SECRET SQL" not in context
    assert "SECRET ROW" not in context


@pytest.mark.asyncio
async def test_vector_provider_requires_current_context_and_reports_disabled_reason(monkeypatch):
    from app.core import settings
    from app.infrastructure.llm.dimension_runtime import retrieve_vector_context

    monkeypatch.setattr(settings, "RAG_ENABLED", False)
    monkeypatch.setattr(
        "app.infrastructure.context.planning_context_factory.get_cached_context",
        lambda _session_id: SimpleNamespace(
            session_id="session-rag-default-disabled",
            village_name="金田村",
            data_snapshot=SimpleNamespace(digest="bundle-digest"),
        ),
    )

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
