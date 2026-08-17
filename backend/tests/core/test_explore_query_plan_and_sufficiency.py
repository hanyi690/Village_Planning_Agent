import pytest


def _request(**updates):
    from app.contracts.evidence.evidence_contracts import ExplorationRequest

    payload = {
        "run_id": "run-1",
        "request_type": "evidence_gap",
        "query": "道路服务范围",
        "stage": "L3",
        "dimension_key": "traffic",
        "query_purpose": "gap_resolution",
        "required_facts": ["道路服务范围"],
        "entity_scope": ["roads"],
    }
    payload.update(updates)
    return ExplorationRequest(**payload)


def test_router_selects_only_required_sources_for_spatial_context():
    from app.evidence.retrieval.router import RetrieverKind, route_request

    routed = route_request(_request(request_type="spatial_lookup", query_purpose="context_injection", required_facts=[]))
    assert routed == [RetrieverKind.REPORT, RetrieverKind.KG, RetrieverKind.BUNDLE]

    gap_routed = route_request(_request())
    assert RetrieverKind.ARTIFACT in gap_routed
    assert RetrieverKind.HISTORY in gap_routed


def test_query_plan_fingerprint_covers_questions_and_scope():
    from app.evidence.retrieval.query_planner import build_query_plan

    first = build_query_plan(_request())
    second = build_query_plan(_request(questions=["道路是否连通"])).request_fingerprint
    assert first.request_fingerprint != second
    assert {query.retriever for query in first.queries}
    assert all(query.required_facts == ("道路服务范围",) for query in first.queries)


@pytest.mark.parametrize(
    ("facts", "sources", "status"),
    [
        (["道路服务范围"], ["report:L3:traffic"], "sufficient"),
        (["道路存在"], ["report:L3:traffic"], "missing_fact"),
        (["道路北侧", "道路南侧"], ["report:L3:traffic"], "ambiguous"),
        ([], [], "source_unavailable"),
        (["道路存在"], ["bundle:lines:transport"], "insufficient_geometry"),
    ],
)
def test_sufficiency_distinguishes_gate_outcomes(facts, sources, status):
    from app.contracts.evidence.evidence_contracts import EvidenceBundle, EvidenceFact, EvidenceSource, ExplorationResult
    from app.evidence.retrieval.sufficiency import evaluate_sufficiency

    result = ExplorationResult(
        evidence_bundle=EvidenceBundle(
            request="道路服务范围",
            facts=[EvidenceFact(statement=fact, source_refs=sources) for fact in facts],
            sources=[EvidenceSource(source_type="report", reference=source) for source in sources],
        )
    )
    request = _request(
        required_facts=["道路服务范围"],
        entity_scope=[] if status in {"sufficient", "missing_fact", "ambiguous"} else ["roads"],
    )
    assert evaluate_sufficiency(request, result).status.value == status
