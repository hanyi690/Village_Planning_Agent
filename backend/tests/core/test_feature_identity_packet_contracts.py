from app.contracts.evidence.evidence_packet_contracts import (
    EvidencePacket,
    SpatialRelationEvidence,
)
from app.contracts.evidence.feature_identity_contracts import (
    BundleFeatureIdentity,
    FeatureEvidenceRef,
)


def test_feature_ref_exposes_distinct_authority_semantic_and_spatial_scores() -> None:
    from types import SimpleNamespace

    from app.evidence.retrieval.evidence_graph import feature_ref_from_candidate

    candidate = SimpleNamespace(
        entity_ref="poi:facility:1",
        canonical_name="祠",
        entity_type="facility",
        role="facility",
        aliases=["祠"],
        feature_bsm="44142621100000000001",
        source_feature_id="feature:1",
        source_layer="current_facility",
        source_bsm="44142621100000000001",
        source_bsms=["44142621100000000001"],
        anchor_bsms=[],
        related_parcel_bsms=[],
        geometry_ref="bundle://feature/44142621100000000001",
        relation_refs=[],
        evidence_refs=["bundle:feature:1"],
        l1_fact_refs=[],
        l1_snapshot_ref="",
        score=2.5,
        evidence={
            "exact_canonical_alias": 1.0,
            "entity_type_role": 0.5,
            "relation_topology": 0.5,
            "within_bundle": 0.5,
        },
    )

    ref = feature_ref_from_candidate(candidate)

    assert ref.source_authority_score == 1.0
    assert ref.semantic_match_score == 0.6
    assert ref.spatial_support_score == 0.6667
    assert ref.external_support_score == 0.0
    assert ref.retrieval_score == 0.5814
    assert ref.selection_confidence is None


def test_feature_identity_preserves_source_and_generated_identity() -> None:
    identity = BundleFeatureIdentity(
        bundle_feature_bsm="441426211000000123",
        admin_code_12="441426211000",
        sequence_code_8="00000123",
        source_feature_id="upload:facilities:7",
        source_layer="facilities_current",
        source_bsm="source-bsm-7",
        bsm_kind="synthetic",
        geometry_digest="sha256:geometry",
        bundle_snapshot_digest="sha256:bundle",
    )
    ref = FeatureEvidenceRef(
        identity=identity,
        entity_refs=["http://example.test/facility-1"],
        geometry_ref="bundle:facilities_current:441426211000000123",
        relation_refs=["rel:located-in:1"],
        related_parcel_bsms=["441426211000000001"],
    )

    assert ref.identity.bundle_feature_bsm == "441426211000000123"
    assert ref.identity.source_bsm == "source-bsm-7"
    assert ref.geometry_authority == "bundle"


def test_evidence_packet_is_bounded_and_relation_provenance_is_explicit() -> None:
    subject = FeatureEvidenceRef(
        identity=BundleFeatureIdentity(bundle_feature_bsm="441426211000000001")
    )
    object_ref = FeatureEvidenceRef(
        identity=BundleFeatureIdentity(bundle_feature_bsm="441426211000000002")
    )
    relation = SpatialRelationEvidence(
        relation_id="rel:near:1",
        subject=subject,
        predicate="near",
        object=object_ref,
        metric_value=12.5,
        metric_unit="m",
        tolerance=1.0,
        crs="EPSG:3857",
        computation_method="postgis_st_dwithin",
        provenance_refs=["bundle:sha256:bundle"],
    )
    packet = EvidencePacket(
        request="xx村的祠堂的BSM",
        bundle_snapshot_digest="sha256:bundle",
        candidate_refs=[subject],
        relation_evidence=[relation],
        source_spans=["architecture:table:3"],
        ambiguity_status="resolved",
        sufficiency="sufficient",
    )

    dumped = packet.model_dump(mode="json")
    assert "full_report" not in dumped
    assert dumped["relation_evidence"][0]["computation_method"] == "postgis_st_dwithin"
