import pytest

from app.contracts.domain.l1_contracts import L1Fact, L1Snapshot
from app.contracts.evidence.evidence_contracts import EvidenceBundle, EvidenceFact
from app.domain.assessment.gate import evaluate_l1_gate
from app.domain.assessment.aggregate import merge_l1_snapshots
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
                fact_id="l1:fact:road-count",
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


def test_report_chapters_with_same_heading_are_not_fact_contradictions():
    snapshot = merge_l1_snapshots(
        [
            L1Snapshot(facts=["[infrastructure] 现状概况: 已建供水管道"]),
            L1Snapshot(facts=["[infrastructure] 现状概况: 采用分散排水"]),
        ],
        run_id="run-report-facts",
    )

    assert not any(item.code == "fact_contradiction" for item in snapshot.issues)


def test_subtype_refines_a_generic_semantic_type():
    def subtype_fact(fact_id: str, subtype: str, value: float) -> L1Fact:
        return L1Fact(
            fact_id=fact_id,
            statement=f"forest_area/{subtype} {value}",
            fact_kind="document_observation",
            dimension_key="ecological_green",
            subject_scope="金田村",
            semantic_type="forest_area",
            attributes={"metric": "forest_area", "subtype": subtype},
            value=value,
            unit="公顷",
            source_refs=[f"source:{fact_id}"],
        )

    snapshot = merge_l1_snapshots(
        [
            L1Snapshot(
                fact_records=[
                    subtype_fact("commercial", "commercial_forest", 1867.38),
                    subtype_fact("ecological", "ecological_forest", 325.92),
                ]
            )
        ],
        run_id="run-subtype-identity",
    )

    assert not any(item.code == "fact_contradiction" for item in snapshot.issues)


def test_comparable_typed_l1_values_are_fact_contradictions():
    def fact(fact_id: str, value: int) -> L1Fact:
        return L1Fact(
            fact_id=fact_id,
            statement=f"常住人口 {value} 人",
            fact_kind="document_observation",
            dimension_key="socio_economic",
            subject_scope="金田村",
            semantic_type="resident_population",
            value=value,
            unit="人",
            counting_basis="2023年统计",
            source_refs=[f"source:{fact_id}"],
        )

    snapshot = merge_l1_snapshots(
        [L1Snapshot(fact_records=[fact("population-a", 500)]),
         L1Snapshot(fact_records=[fact("population-b", 600)])],
        run_id="run-typed-conflict",
    )

    issue = next(item for item in snapshot.issues if item.code == "fact_contradiction")
    assert "socio_economic" in issue.message


def test_categorical_constraint_variants_do_not_block_l1_gate():
    def constraint(fact_id: str, value: str) -> L1Fact:
        return L1Fact(
            fact_id=fact_id,
            statement=f"地质灾害 {value}",
            fact_kind="document_observation",
            dimension_key="land_use",
            subject_scope="金田村",
            semantic_type="constraint",
            attributes={"fact_type": "constraint", "name": "hazard_point_constraint"},
            value=value,
            source_refs=[f"source:{fact_id}"],
        )

    snapshot = merge_l1_snapshots(
        [
            L1Snapshot(fact_records=[constraint("hazard-a", "易发生区")]),
            L1Snapshot(fact_records=[constraint("hazard-b", "中易发生区")]),
        ],
        run_id="run-categorical-constraint-variant",
    )
    snapshot.facts = ["地质灾害易发生区"]
    snapshot.sources = [{"source_type": "report", "reference": "source:hazard"}]

    assert not any(item.code == "fact_contradiction" for item in snapshot.issues)
    assert evaluate_l1_gate(snapshot).passed is True


def test_different_metrics_in_one_semantic_family_are_not_contradictions():
    def metric(fact_id: str, metric_name: str, value: float) -> L1Fact:
        return L1Fact(
            fact_id=fact_id,
            statement=f"{metric_name} {value}",
            fact_kind="document_observation",
            dimension_key="land_use",
            subject_scope="金田村",
            semantic_type="land_use_composition",
            attributes={"metric": metric_name},
            value=value,
            unit="公顷",
            source_refs=[f"source:{fact_id}"],
        )

    snapshot = merge_l1_snapshots(
        [
            L1Snapshot(fact_records=[metric("total", "total_land_area", 2352.89)]),
            L1Snapshot(fact_records=[metric("agri", "agricultural_land_area", 1960.70)]),
        ],
        run_id="run-independent-metrics",
    )

    assert not any(item.code == "fact_contradiction" for item in snapshot.issues)


def test_distinct_semantic_types_with_generic_metric_are_not_contradictions():
    def area(fact_id: str, semantic_type: str, value: float) -> L1Fact:
        return L1Fact(
            fact_id=fact_id,
            statement=f"{semantic_type} {value}",
            fact_kind="document_observation",
            dimension_key="ecological_green",
            subject_scope="金田村",
            semantic_type=semantic_type,
            attributes={"metric": "area"},
            value=value,
            unit="公顷",
            source_refs=[f"source:{fact_id}"],
        )

    snapshot = merge_l1_snapshots(
        [
            L1Snapshot(
                fact_records=[
                    area("commercial", "forest_area:commercial_forest", 1867.38),
                    area("ecological", "forest_area:ecological_forest", 325.92),
                ]
            ),
            L1Snapshot(
                fact_records=[area("water", "water_area", 35.99)]
            ),
        ],
        run_id="run-semantic-type-identity",
    )

    assert not any(item.code == "fact_contradiction" for item in snapshot.issues)


@pytest.mark.parametrize("attribute_key", ["forest_type", "crop_type", "hazard_type"])
def test_domain_specific_type_attributes_refine_generic_identity(attribute_key: str):
    def typed_fact(fact_id: str, value: float, subtype: str) -> L1Fact:
        return L1Fact(
            fact_id=fact_id,
            statement=f"{attribute_key}={subtype} {value}",
            fact_kind="document_observation",
            dimension_key="mixed_observations",
            subject_scope="金田村",
            semantic_type="area_or_count",
            attributes={attribute_key: subtype},
            value=value,
            unit="项",
            source_refs=[f"source:{fact_id}"],
        )

    snapshot = merge_l1_snapshots(
        [
            L1Snapshot(
                fact_records=[
                    typed_fact("typed-a", 5, "first"),
                    typed_fact("typed-b", 35, "second"),
                ]
            )
        ],
        run_id=f"run-{attribute_key}",
    )

    assert not any(item.code == "fact_contradiction" for item in snapshot.issues)


def test_named_hazard_facts_refine_generic_identity_and_same_name_still_conflicts():
    def named_fact(fact_id: str, name: str, value: int) -> L1Fact:
        return L1Fact(
            fact_id=fact_id,
            statement=f"{name} {value}",
            fact_kind="document_observation",
            dimension_key="ecological_green",
            subject_scope="金田村",
            semantic_type="hazard_point_count",
            attributes={"name": name, "description": "隐患点"},
            value=value,
            unit="处",
            source_refs=[f"source:{fact_id}"],
        )

    distinct = merge_l1_snapshots(
        [
            L1Snapshot(
                fact_records=[
                    named_fact("collapse", "崩塌隐患点", 5),
                    named_fact("landslide", "滑坡隐患点", 35),
                ]
            )
        ],
        run_id="run-named-hazard-types",
    )
    assert not any(item.code == "fact_contradiction" for item in distinct.issues)

    same_name = merge_l1_snapshots(
        [
            L1Snapshot(
                fact_records=[
                    named_fact("same-a", "滑坡隐患点", 5),
                    named_fact("same-b", "滑坡隐患点", 35),
                ]
            )
        ],
        run_id="run-same-named-hazard",
    )
    assert any(item.code == "fact_contradiction" for item in same_name.issues)


def test_relation_endpoints_refine_distance_identity():
    def distance_fact(fact_id: str, destination: str, value: int) -> L1Fact:
        return L1Fact(
            fact_id=fact_id,
            statement=f"泗水镇到{destination} {value}km",
            fact_kind="document_observation",
            dimension_key="location",
            subject_scope="泗水镇",
            semantic_type="distance",
            attributes={
                "fact_type": "scoped_metric",
                "from": "泗水镇",
                "metric": "distance",
                "name": "distance",
                "to": destination,
            },
            value=value,
            unit="km",
            source_refs=[f"source:{fact_id}"],
        )

    snapshot = merge_l1_snapshots(
        [
            L1Snapshot(
                fact_records=[
                    distance_fact("county", "平远县城", 36),
                    distance_fact("city", "梅州市区", 80),
                ]
            )
        ],
        run_id="run-distance-endpoints",
    )

    assert not any(item.code == "fact_contradiction" for item in snapshot.issues)
