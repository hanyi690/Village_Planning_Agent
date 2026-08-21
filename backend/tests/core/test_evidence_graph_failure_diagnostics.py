from types import SimpleNamespace

import pytest

from app.contracts.evidence.evidence_contracts import ExplorationRequest
from app.evidence.retrieval import evidence_service
from app.evidence.retrieval import evidence_graph


@pytest.mark.asyncio
async def test_retrieve_evidence_exposes_graph_failure(monkeypatch) -> None:
    session_id = "evidence-graph-failure-diagnostic"
    context = SimpleNamespace(
        session_id=session_id,
        workspace=None,
        location_facts=[],
        l1_fact_records=[],
        source_semantic_decisions={},
        source_semantic_diagnostics=[],
        source_semantic_fingerprint="",
    )

    def fail_graph(*_args, **_kwargs):
        raise RuntimeError("synthetic graph failure")

    monkeypatch.setattr(
        "app.infrastructure.context.planning_context_factory.get_cached_context",
        lambda _session_id: context,
    )
    monkeypatch.setattr(
        evidence_graph,
        "enrich_evidence_packet_with_spatial_graph",
        fail_graph,
    )
    evidence_service._EVIDENCE_CACHE.clear()

    result = await evidence_service.retrieve_evidence(
        ExplorationRequest(
            run_id=session_id,
            request_type="spatial_lookup",
            query="金田村祠堂的BSM",
            stage="L1",
            dimension_key="location",
            entity_scope=["facilities"],
        ),
        session_id,
        village_name="金田村",
    )

    assert result.evidence_packet is not None
    assert any(
        item.get("step") == "evidence_graph_enrichment"
        and item.get("status") == "failed"
        for item in result.evidence_packet.query_trace
    )
    assert "evidence_graph_unavailable" in result.evidence_packet.missing_evidence

