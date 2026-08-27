from types import SimpleNamespace

import pytest

from app.contracts.evidence.evidence_contracts import (
    EvidenceBundle,
    EvidenceFact,
    EvidenceSource,
    ExplorationResult,
)
from app.contracts.evidence.evidence_packet_contracts import (
    EvidencePacket,
    SpatialRelationEvidence,
)
from app.contracts.evidence.feature_identity_contracts import (
    BundleFeatureIdentity,
    FeatureEvidenceRef,
)
from app.contracts.evidence.requirement_contracts import (
    EvidenceCoverage,
    EvidenceRequirement,
    RequirementCoverage,
)
from app.infrastructure.context.project_cognition import (
    build_project_cognition,
    normalize_source_family,
    render_analysis_evidence,
    render_analysis_evidence_for_prompt,
)


def test_cognition_digest_is_stable_and_scope_isolated():
    context = SimpleNamespace(session_id="s1", village_name="v", version=2, content_hash="d")
    a = build_project_cognition(context, {"spatial_ref": "v"})
    b = build_project_cognition(context, {"spatial_ref": "v"})
    assert a.cognition_digest == b.cognition_digest
    assert a.spatial_scope == {"spatial_ref": "v"}


def test_real_exploration_result_deduplicates_semantic_fact_and_preserves_lineage():
    result = ExplorationResult(
        evidence_bundle=EvidenceBundle(
            request="population",
            facts=[
                EvidenceFact(
                    statement="same",
                    source_refs=["l1:x"],
                    source_locator="p1",
                    fact_type="l1_fact",
                    source_kind="l1_typed_fact",
                    fields={
                        "subject_ref": "place:1",
                        "predicate": "population",
                        "normalized_value": "3000",
                        "geometry_ref": "bundle://geometry/1",
                    },
                ),
                EvidenceFact(
                    statement="same",
                    source_refs=["kg:x"],
                    fact_type="kg_canonical_fact",
                    source_kind="kg_canonical_fact",
                    fields={
                        "subject_ref": "place:1",
                        "predicate": "population",
                        "normalized_value": "3000",
                    },
                ),
            ],
            sources=[
                EvidenceSource(source_type="l1", reference="l1:x", snapshot_ref="l1:s"),
                EvidenceSource(source_type="kg", reference="kg:x", snapshot_ref="kg:s"),
            ],
        )
    )

    projected = render_analysis_evidence(result)

    assert len(projected["facts"]) == 1
    fact = projected["facts"][0]
    assert fact["source_refs"] == ["kg:x", "l1:x"]
    assert fact["evidence_refs"] == []
    assert fact["lineage_refs"] == ["kg:s", "kg:x", "l1:s", "l1:x", "p1"]
    assert fact["geometry_ref"] == "bundle://geometry/1"
    assert fact["snapshot_refs"] == ["kg:s", "l1:s"]
    assert set(fact["source_families"]) == {"kg", "l1"}
    assert set(fact["source_kinds"]) == {"kg_canonical_fact", "l1_typed_fact"}


def test_packet_candidates_and_relations_become_separate_facts():
    subject = FeatureEvidenceRef(
        identity=BundleFeatureIdentity(
            bundle_feature_bsm="feature-1",
            canonical_name="祠堂",
            entity_type="facility",
            role="facility",
            bsm_kind="source",
            bundle_snapshot_digest="bundle:s1",
        ),
        entity_refs=["entity:1"],
        geometry_ref="bundle://feature/feature-1",
        relation_refs=["relation:1"],
        provenance_refs=["bundle:facilities"],
        l1_fact_refs=["l1:fact:1"],
        l1_snapshot_ref="l1:s1",
    )
    object_ref = FeatureEvidenceRef(
        identity=BundleFeatureIdentity(
            bundle_feature_bsm="feature-2",
            canonical_name="道路",
            entity_type="road",
            bsm_kind="source",
        ),
        geometry_ref="bundle://feature/feature-2",
    )
    result = ExplorationResult(
        evidence_bundle=EvidenceBundle(request="nearby"),
        evidence_packet=EvidencePacket(
            request="nearby",
            bundle_snapshot_digest="bundle:s1",
            l1_snapshot_ref="l1:s1",
            candidate_refs=[subject],
            relation_evidence=[
                SpatialRelationEvidence(
                    relation_id="relation:1",
                    subject=subject,
                    predicate="near",
                    object=object_ref,
                    metric_value=12.5,
                    metric_unit="m",
                    provenance_refs=["kg:relation-source"],
                )
            ],
            source_spans=["full report span"],
            query_trace=[{"sql": "secret"}],
        ),
    )

    projected = render_analysis_evidence(result)
    candidate_fact = next(item for item in projected["facts"] if item["fact_key"] == "bundle_feature_identity")
    relation_fact = next(item for item in projected["facts"] if item["fact_key"] == "spatial_relation")

    assert candidate_fact["source_refs"] == ["bundle:facilities", "bundle:feature:feature-1"]
    assert candidate_fact["evidence_refs"] == ["l1:fact:1", "relation:1"]
    assert candidate_fact["geometry_ref"] == "bundle://feature/feature-1"
    assert candidate_fact["snapshot_refs"] == ["bundle:s1", "l1:s1"]
    assert relation_fact["source_refs"] == ["kg:relation-source"]
    assert relation_fact["evidence_refs"] == ["relation:1"]
    assert relation_fact["geometry_ref"] == "bundle://feature/feature-1"
    assert relation_fact["attributes"]["object_geometry_ref"] == "bundle://feature/feature-2"
    assert "secret" not in str(projected)
    assert "full report span" not in str(projected)


def test_conflicting_values_keep_variants_with_unique_fact_ids():
    facts = [
        EvidenceFact(
            statement="人口为 3000",
            source_refs=["report:a"],
            source_kind="analysis_report",
            fields={
                "fact_id": "population@2024",
                "subject_ref": "village:1",
                "predicate": "population",
                "normalized_value": "3000",
            },
        ),
        EvidenceFact(
            statement="人口为 3500",
            source_refs=["bundle:stats"],
            source_kind="bundle_layer_stat",
            fields={
                "fact_id": "population@2024",
                "subject_ref": "village:1",
                "predicate": "population",
                "normalized_value": "3500",
            },
        ),
    ]
    result = ExplorationResult(
        evidence_bundle=EvidenceBundle(request="population", facts=facts)
    )

    projected = render_analysis_evidence(result)
    variants = projected["facts"]

    assert len(variants) == 2
    assert len({item["fact_id"] for item in variants}) == 2
    assert {item["normalized_value"] for item in variants} == {"3000", "3500"}
    assert len({item["conflict_group_id"] for item in variants}) == 1
    assert variants[0]["status"] == variants[1]["status"] == "conflict"
    assert len(projected["conflicts"]) == 1
    assert set(projected["conflicts"][0]["fact_refs"]) == {item["fact_id"] for item in variants}


def test_source_kind_mapping_and_coverage_are_exact_and_safe():
    assert normalize_source_family("external_search") == "external"
    assert normalize_source_family("analysis_report") == "text"
    assert normalize_source_family("external_search_result") == "unknown"
    requirement = EvidenceRequirement(requirement_id="req:road", statement="road access")
    coverage = EvidenceCoverage(
        requirement_set_fingerprint="req-fingerprint",
        requirements=(requirement,),
        requirement_coverage=(
            RequirementCoverage(
                requirement_id="req:road",
                status="unresolved",
                unresolved_reason="not found",
            ),
        ),
        unresolved_requirements=("req:road",),
        stop_reason="source_exhausted",
        query_trace=({"sql": "secret"},),
    )
    result = ExplorationResult(
        evidence_bundle=EvidenceBundle(request="road access"), coverage=coverage
    )

    projected = render_analysis_evidence(result)

    assert set(projected) == {"facts", "sources", "conflicts", "coverage", "gap"}
    assert "query_trace" not in str(projected)
    assert projected["coverage"]["requirement_coverage"][0]["status"] == "unresolved"
    assert projected["gap"] == [
        {"gap_id": "req:road", "status": "unresolved", "reason": "not found"}
    ]


def test_analysis_projection_requires_the_real_result_contract():
    with pytest.raises(TypeError):
        render_analysis_evidence(object())


def test_analysis_projection_applies_deterministic_bounds_to_every_projection_plane():
    facts = [
        EvidenceFact(
            statement="x" * 2000,
            source_refs=[f"source:{index}" for index in range(20)],
            source_kind="l1",
            fields={
                "subject_ref": f"place:{index}",
                "predicate": "population",
                "normalized_value": str(index),
                "body": "secret",
            },
        )
        for index in range(6)
    ]
    coverage = EvidenceCoverage(
        requirement_set_fingerprint="fingerprint",
        stop_reason="source_exhausted",
        requirements=tuple(
            EvidenceRequirement(requirement_id=f"req:{index}", statement="y")
            for index in range(6)
        ),
        requirement_coverage=tuple(
            RequirementCoverage(
                requirement_id=f"req:{index}",
                status="unresolved",
                unresolved_reason="r" * 2000,
            )
            for index in range(6)
        ),
        unresolved_requirements=tuple(f"req:{index}" for index in range(6)),
    )
    result = ExplorationResult(
        evidence_bundle=EvidenceBundle(
            request="q" * 2000,
            facts=facts,
            sources=[EvidenceSource(source_type="l1", reference=f"source:{index}") for index in range(6)],
        ),
        coverage=coverage,
    )

    projected = render_analysis_evidence(result, budget=2)

    assert all(len(projected[key]) <= 2 for key in ("facts", "sources", "conflicts", "gap"))
    assert len(projected["coverage"]["requirement_coverage"]) <= 2
    assert len(projected["facts"][0]["statement"]) <= 512
    assert len(projected["facts"][0]["source_refs"]) <= 32
    assert "secret" not in str(projected)
    assert "body" not in str(projected)


def test_prompt_projection_keeps_semantics_without_repeating_retrieval_payload():
    result = ExplorationResult(
        evidence_bundle=EvidenceBundle(
            request="道路",
            facts=[EvidenceFact(
                statement="村道位于东侧" * 100,
                source_refs=[f"source:{index}" for index in range(20)],
                source_kind="kg_canonical_fact",
                fields={
                    "subject_ref": "feature:road-1",
                    "predicate": "access",
                    "normalized_value": "东侧",
                    "body": "不应进入分析提示词",
                    **{
                        f"attribute-{index}": "value" * 500
                        for index in range(20)
                    },
                },
            )],
        )
    )

    projected = render_analysis_evidence_for_prompt(result)

    assert len(projected["facts"]) == 1
    assert len(projected["facts"][0]["statement"]) <= 320
    assert len(projected["facts"][0]["source_refs"]) <= 4
    assert len(projected["facts"][0]["attributes"]) <= 4
    assert "body" not in str(projected)
    assert "不应进入分析提示词" not in str(projected)
