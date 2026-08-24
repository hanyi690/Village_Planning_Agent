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


@pytest.mark.asyncio
async def test_gap_loop_only_queries_missing_requirements_and_stops_when_resolved(monkeypatch):
    from app.contracts.evidence.evidence_contracts import (
        EvidenceBundle,
        EvidenceSource,
        ExplorationResult,
    )
    from app.contracts.evidence.evidence_packet_contracts import EvidencePacket
    from app.contracts.evidence.requirement_contracts import (
        EvidenceCoverage,
        EvidenceRequirement,
        RequirementCoverage,
    )
    from app.evidence.retrieval import evidence_service as service

    service._EVIDENCE_CACHE.clear()
    service._GATE_EVIDENCE_CACHE.clear()
    calls = []
    requirement = EvidenceRequirement(
        requirement_id="req-road-class",
        request_id="session-gap",
        statement="道路等级",
        source_families=("report",),
    )

    def result_for(request, *, unresolved):
        coverage = EvidenceCoverage(
            run_id=request.run_id,
            request_id=request.run_id,
            requirement_set_fingerprint="fingerprint-road-class",
            source_families_queried=("report",),
            requirements=(requirement,),
            requirement_coverage=(RequirementCoverage(
                requirement_id=requirement.requirement_id,
                status="unresolved" if unresolved else "supported",
                locators_complete=not unresolved,
            ),),
            unresolved_requirements=(requirement.requirement_id,) if unresolved else (),
            stop_reason="source_exhausted" if unresolved else "sufficient",
        )
        return ExplorationResult(
            evidence_bundle=EvidenceBundle(
                request=request.query,
                sources=[EvidenceSource(source_type="report", reference="report:road")],
                unresolved=[requirement.statement] if unresolved else [],
            ),
            evidence_packet=EvidencePacket(
                request=request.query,
                missing_evidence=[requirement.statement] if unresolved else [],
            ),
            coverage=coverage,
        )

    async def fake_retrieve(request, *args, **kwargs):
        calls.append(request)
        return result_for(request, unresolved=len(calls) == 1)

    monkeypatch.setattr(service, "retrieve_evidence", fake_retrieve)
    gate = {
        "feedback_route": "EXPLORE",
        "stage": "L3",
        "pending_requests": [{
            "request_type": "evidence_gap",
            "context": {
                "dimension": "traffic",
                "message": "道路相关约束",
                "required_fact": ["道路等级", "道路宽度"],
                "entity_scope": ["roads"],
            },
        }],
    }

    results = await service.retrieve_evidence_for_gate(gate, "session-gap")

    assert len(results) == 2
    assert len(calls) == 2
    assert calls[1].query == "道路等级"
    assert calls[1].required_facts == ["道路等级"]
    assert calls[1].query_purpose == "gap_resolution"
    assert results[0].evidence_packet.query_trace[-1]["status"] == "follow_up_requested"
    assert results[1].evidence_packet.query_trace[-1]["status"] == "sufficient"
