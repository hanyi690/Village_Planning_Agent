from app.contracts.domain.l1_contracts import L1Fact, L1Snapshot
from app.contracts.evidence.evidence_contracts import EvidenceBundle, EvidenceFact
from app.domain.assessment.gate import evaluate_l1_gate
from app.evidence.retrieval.fact_quality import apply_fact_quality, evaluate_fact_quality


def _count(
    statement: str,
    value: int,
    *,
    basis: str = "source_feature",
    scope: str = "Road",
    snapshot: str = "snapshot:current",
    collection: str = "current_road",
    source_ids: str = "r-1,r-2",
) -> EvidenceFact:
    return EvidenceFact(
        statement=statement,
        source_refs=[f"test:{statement}"],
        fact_type="kg_canonical_fact",
        fields={
            "fact_id": statement,
            "value": str(value),
            "unit": "source_features",
            "counting_basis": basis,
            "subject_scope": scope,
            "source_collection_key": collection,
            "source_snapshot_ref": snapshot,
            "source_feature_ids": source_ids,
        },
    )


def test_legacy_275_is_not_a_legitimate_mismatch_with_131_current_features():
    legacy = _count(
        "KG实体统计: 道路 275 个",
        275,
        snapshot="",
        collection="",
        source_ids="",
    )
    current = _count("当前道路源集合: 131 条", 131, source_ids="r-1,r-2,r-3")

    report = evaluate_fact_quality([legacy, current])

    by_statement = {fact.statement: fact for fact in report.facts}
    assert "unverified" in by_statement[legacy.statement].support_relations
    assert "unverified" not in by_statement[current.statement].support_relations
    assert not any(item.relation == "contradicts" for item in report.conflicts)


def test_comparable_counts_are_contradictions_but_different_basis_is_not():
    current = _count("current roads", 131, source_ids="r-1,r-2")
    changed = _count("current roads changed", 129, source_ids="r-1,r-3")
    business = _count(
        "business road objects",
        80,
        basis="business_object",
        collection="road_business_objects",
        source_ids="b-1,b-2",
    )

    report = evaluate_fact_quality([current, changed, business])

    assert any(item.relation == "contradicts" for item in report.conflicts)
    assert any(item.relation == "different_counting_basis" for item in report.conflicts)
    assert all("contradicts" in fact.support_relations for fact in report.facts[:2])


def test_unverified_quantitative_fact_is_exposed_as_an_evidence_gap():
    bundle = EvidenceBundle(
        request="道路数量",
        facts=[
            _count(
                "没有来源身份的道路数量",
                275,
                snapshot="",
                collection="",
                source_ids="",
            )
        ],
    )

    result = apply_fact_quality(bundle)

    assert result.conflicts == []
    assert result.unresolved
    assert result.facts[0].status == "needs_review"


def test_l1_gate_routes_unverified_source_feature_counts_to_explore():
    snapshot = L1Snapshot(
        fact_records=[
            L1Fact(
                fact_id="l1:road-count",
                statement="道路 275 个",
                fact_kind="kg_canonical_fact",
                value=275,
                unit="source_features",
                counting_basis="source_feature",
                source_refs=["kg:legacy-count"],
            )
        ],
        facts=["道路 275 个"],
    )

    decision = evaluate_l1_gate(snapshot)

    assert decision.passed is False
    assert decision.feedback_route == "EXPLORE"
    assert decision.pending_requests[0].request_type == "evidence_gap"
