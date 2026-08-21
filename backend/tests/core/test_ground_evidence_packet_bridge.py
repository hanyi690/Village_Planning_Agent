from types import SimpleNamespace

from app.contracts.evidence.evidence_packet_contracts import (
    EvidencePacket,
    SpatialRelationEvidence,
)
from app.contracts.evidence.feature_identity_contracts import (
    BundleFeatureIdentity,
    FeatureEvidenceRef,
)
from app.contracts.planning.intent_graph import PlanRelationIntent, PlanningIntentGraph
from app.contracts.planning.relation_parameters import DistanceParameters
from app.contracts.spatial.spatial_reference_contracts import RefObject, SpatialReferenceSpec
from app.domain.ground.aggregate import ground_aggregate
from app.spatial.grounding.resolver import SpatialResolver


def _context():
    feature = SimpleNamespace(
        bsm="44142621100000000123",
        source_feature_id="facility-source-1",
        ysdm="facility-source-1",
        geometry={"type": "Point", "coordinates": [116.0, 24.0]},
    )
    workspace = SimpleNamespace(
        points=SimpleNamespace(
            get=lambda key: [feature] if key == "facilities_current" else [],
            keys=lambda: ["facilities_current"],
        ),
        lines=SimpleNamespace(get=lambda _key: [], keys=lambda: []),
        polygons=SimpleNamespace(get=lambda _key: [], keys=lambda: []),
        metadata=SimpleNamespace(crs="EPSG:4326"),
    )
    return SimpleNamespace(
        session_id="packet-ground-bridge",
        village_name="社前村",
        workspace=workspace,
        kg=None,
        gazetteer=None,
        constraint_index=None,
        ports=SimpleNamespace(spatial_query=None),
        current_parcels=lambda: [],
        data_snapshot=SimpleNamespace(digest="bundle-digest-packet-bridge"),
        l1_snapshot_ref="artifact://l1/packet-bridge",
    )


def _packet() -> EvidencePacket:
    return EvidencePacket(
        request="社前村祠堂",
        bundle_snapshot_digest="bundle-digest-packet-bridge",
        l1_snapshot_ref="artifact://l1/packet-bridge",
        ambiguity_status="resolved",
        candidate_refs=[
            FeatureEvidenceRef(
                identity=BundleFeatureIdentity(
                    bundle_feature_bsm="44142621100000000123",
                    source_feature_id="facility-source-1",
                    source_layer="facilities_current",
                    bsm_kind="source",
                    bundle_snapshot_digest="bundle-digest-packet-bridge",
                ),
                entity_refs=["kg:facility:1"],
                geometry_ref="bundle://feature/44142621100000000123",
                relation_refs=["relation:within-village"],
                l1_fact_refs=["l1:fact:facility-1"],
                l1_snapshot_ref="artifact://l1/packet-bridge",
                source_authority_score=1.0,
                semantic_match_score=0.96,
                spatial_support_score=0.96,
                retrieval_score=0.96,
            )
        ],
    )


def test_spatial_resolver_reads_packet_geometry_only_from_bundle() -> None:
    context = _context()
    spec = SpatialReferenceSpec(
        type="attributive",
        reference=RefObject(kind="place_name", filter={"label_contains": "祠堂"}),
        target_id="facility-1",
    )

    resolved = SpatialResolver(context).resolve_spec(
        spec,
        evidence_packet=_packet(),
    )

    assert resolved.spatial_domain_kind == "exact_feature"
    assert resolved.reference_geometries
    geometry = resolved.reference_geometries[0]
    assert geometry.wkt == "POINT (116 24)"
    assert geometry.source_ref == "bundle:facilities_current:44142621100000000123"
    assert geometry.feature_bsms == ["44142621100000000123"]
    assert "bundle://feature/44142621100000000123" in geometry.source_refs
    assert "evidence_packet" in str(resolved.provenance.get("path"))


def test_ground_aggregate_promotes_packet_candidate_to_typed_geometry() -> None:
    context = _context()
    spec = SpatialReferenceSpec(
        type="attributive",
        reference=RefObject(kind="place_name", filter={"label_contains": "祠堂"}),
        target_id="facility-1",
    )

    result = ground_aggregate(
        [spec],
        context,
        target_metadata={
            "facility-1": {
                "target_kind": "facility",
                "expected_output_kind": "point",
            }
        },
        evidence_packets={"facility-1": _packet()},
    )

    assert len(result.candidates) == 1
    candidate = result.candidates[0]
    assert candidate.geometry is not None
    assert candidate.geometry.kind == "point"
    assert candidate.geometry.feature_bsms == ["44142621100000000123"]
    assert candidate.geometry.entity_refs == ["kg:facility:1"]
    assert candidate.geometry.relation_refs == ["relation:within-village"]
    assert candidate.geometry.l1_fact_refs == ["l1:fact:facility-1"]
    assert candidate.geometry.bundle_snapshot_digest == "bundle-digest-packet-bridge"


def test_composed_ground_spec_keeps_parent_packet_geometry_and_lineage() -> None:
    context = _context()
    spec = SpatialReferenceSpec(
        type="composed",
        op="and",
        children=[
            SpatialReferenceSpec(
                type="attributive",
                reference=RefObject(
                    kind="place_name",
                    filter={"label_contains": "祠堂"},
                ),
            ),
            SpatialReferenceSpec(
                type="topological",
                reference=RefObject(
                    kind="place_name",
                    filter={"label_contains": "社前村"},
                ),
                topo="sfWithin",
            ),
        ],
        target_id="facility-composed-1",
    )

    resolved = SpatialResolver(context).resolve_spec(
        spec,
        evidence_packet=_packet(),
    )

    assert resolved.reference_geometry_wkt == "POINT (116 24)"
    assert resolved.spatial_domain_kind == "exact_feature"
    assert "composed:and+evidence_packet" in str(
        resolved.provenance.get("path")
    )
    assert resolved.provenance["relation_refs"] == ["relation:within-village"]
    assert resolved.provenance["l1_fact_refs"] == ["l1:fact:facility-1"]


def test_declared_relation_absorbs_packet_topology_without_creating_implicit_hard_constraint() -> None:
    context = _context()
    spec = SpatialReferenceSpec(
        type="attributive",
        reference=RefObject(kind="place_name", filter={"label_contains": "祠堂"}),
        target_id="facility-1",
    )
    reference = FeatureEvidenceRef(
        identity=BundleFeatureIdentity(
            bundle_feature_bsm="44142621100000000999",
            canonical_name="公共服务点",
            entity_type="facility",
            source_layer="facilities_current",
            bsm_kind="source",
            bundle_snapshot_digest="bundle-digest-packet-bridge",
        ),
        entity_refs=["kg:facility:reference"],
        geometry_ref="bundle://feature/44142621100000000999",
        l1_fact_refs=["l1:fact:reference"],
    )
    packet = _packet().model_copy(update={
        "relation_evidence": [
            SpatialRelationEvidence(
                relation_id="relation:facility-near-reference",
                subject=_packet().candidate_refs[0],
                predicate="nearby",
                object=reference,
                provenance_refs=["kg:relation:source"],
            )
        ]
    })
    intent_graph = PlanningIntentGraph(
        relations=[
            PlanRelationIntent(
                relation_id="near-facility-reference",
                relation_template="near",
                subject_ref="facility-1",
                object_ref="kg:facility:reference",
                object_ref_kind="entity",
                criticality="hard",
                parameters=DistanceParameters(
                    max_distance_m=500.0,
                    metric="euclidean",
                ),
            )
        ]
    )

    result = ground_aggregate(
        [spec],
        context,
        intent_graph=intent_graph,
        target_metadata={
            "facility-1": {
                "target_kind": "facility",
                "expected_output_kind": "point",
            }
        },
        evidence_packets={"facility-1": packet},
    )

    assert len(result.constraint_factors) == 1
    factor = result.constraint_factors[0]
    assert factor.hard is True
    assert "kg:relation:relation:facility-near-reference" in factor.evidence_refs
    assert "relation:facility-near-reference:nearby" in factor.detail
    assert result.relation_satisfaction[0].status in {"unknown", "deferred"}
    assert any(
        item.query_type == "evidence_packet_relation"
        and item.target_id == "facility-1"
        and "relation:facility-near-reference" in item.result_refs
        for item in result.spatial_query_evidence
    )
