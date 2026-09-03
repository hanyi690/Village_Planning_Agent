import hashlib

import pytest
from rdflib import Graph, RDF

from app.contracts.artifacts.ref import ArtifactRef
from app.contracts.cognition.identity_projection import (
    IdentityBindingCommitEnvelope,
)
from app.contracts.cognition.query import (
    IdentityBindingProjectionRequest,
)
from app.contracts.evidence.identity_contracts import (
    EvidenceObservation,
    EvidenceObservationSnapshot,
    GroundedEntityBinding,
    GroundedEntityBindingSnapshot,
)
from app.contracts.evidence.external_observation_contracts import (
    ExternalObservation,
    ExternalObservationSnapshot,
)
from app.infrastructure.kg.adapters.external_observation_adapter import (
    project_external_observations,
)
from app.infrastructure.kg.ontology import GEO, PLN
from app.infrastructure.artifacts.fingerprint import semantic_checksum
from app.infrastructure.cognition_runtime.world_model_store import (
    WorldModelKGStore,
)
from app.infrastructure.context_runtime.cognition_projection import (
    ContextProjectionRuntime,
)
from app.data.resource_catalog import DataResourceCatalog


def _artifact_ref(payload, *, schema_id: str, label: str) -> ArtifactRef:
    digest = hashlib.sha256(label.encode("utf-8")).hexdigest()
    descriptor = hashlib.sha256(
        ("descriptor:" + label).encode("utf-8")
    ).hexdigest()
    return ArtifactRef(
        digest="sha256:" + digest,
        descriptor_digest="sha256:" + descriptor,
        size_bytes=1,
        schema_id=schema_id,
        schema_version="3",
        semantic_digest="sha256:" + semantic_checksum(payload),
        producer_stage="test",
        run_id="run-identity",
        branch_id="main",
    )


def test_adapter_keeps_support_cluster_separate_from_world_entity_types():
    snapshot = ExternalObservationSnapshot(
        snapshot_id="snap-kg",
        observations=[
            ExternalObservation(
                observation_id="a-1",
                provider="amap",
                stage="l1",
                observed_name="村道",
                observed_type="road",
                location_wgs84=(113.0, 23.0),
                cluster_id="cluster-1",
                coordinate_contract="WGS84 direct",
                coordinate_source_crs="WGS84",
                coordinate_target_crs="WGS84",
                coordinate_trust_status="verified_direct",
                spatial_evidence_role="feature_location",
            ),
            ExternalObservation(
                observation_id="t-1",
                provider="tianditu",
                stage="l1",
                observed_name="道路",
                aliases=("村道",),
                observed_type="road",
                location_wgs84=(113.0001, 23.0001),
                cluster_id="cluster-1",
                coordinate_contract="WGS84 direct",
                coordinate_source_crs="WGS84",
                coordinate_target_crs="WGS84",
                coordinate_trust_status="verified_direct",
                spatial_evidence_role="feature_location",
            ),
        ],
    )
    graph = Graph()
    supports = project_external_observations(graph, snapshot)
    assert len(supports) == 1
    support_uri = next(graph.subjects(RDF.type, PLN.ExternalObservationSupport))
    assert len(list(graph.objects(support_uri, PLN.externalObservation))) == 2
    assert not list(graph.subjects(RDF.type, PLN.Road))
    assert not list(graph.subjects(RDF.type, PLN.Parcel))
    assert not any(str(predicate).endswith("asWKT") for _, predicate, _ in graph)
    assert all(
        str(ref).count("external-observation:") == 1
        for ref in graph.objects(None, PLN.observationRef)
    )


def test_adapter_keeps_unverified_observation_advisory_only():
    snapshot = ExternalObservationSnapshot(
        snapshot_id="snap-kg-unverified",
        observations=[
            ExternalObservation(
                observation_id="external-observation:external-observation:td-1",
                provider="tianditu",
                stage="l1",
                observed_name="金田村",
                aliases=["金田"],
                location_wgs84=(113.0, 23.0),
                coordinate_contract="WGS84-compatible",
                coordinate_source_crs="WGS84",
                coordinate_target_crs="WGS84",
                coordinate_trust_status="unverified",
            )
        ],
    )
    graph = Graph()
    project_external_observations(graph, snapshot)
    assert not any(str(predicate).endswith("asWKT") for _, predicate, _ in graph)
    assert list(graph.objects(None, PLN.provider))
    assert list(graph.objects(None, PLN.coordinateTrustStatus))
    assert list(graph.objects(None, PLN.supportAlias))


def test_identity_binding_commit_is_atomic_bounded_and_idempotent(tmp_path):
    records = [
        {
            "source_feature_ref": "road-segment-1",
            "source_crs": "EPSG:4326",
            "geometry": {
                "type": "LineString",
                "coordinates": [[113.0, 23.0], [113.001, 23.001]],
            },
            "properties": {"source_name": "村道"},
        }
    ]
    draft_catalog = DataResourceCatalog.from_records(
        records,
        dataset_ref="dataset:identity-test",
        name="identity-test",
    )
    feature = draft_catalog.snapshot.features[0]
    catalog = DataResourceCatalog.from_records(
        records,
        dataset_ref="dataset:identity-test",
        name="identity-test",
        admission_decisions=[{
            "decision_ref": "admission:road-segment-1",
            "source_ref": (
                f"resource:{feature.dataset_ref}:"
                f"{feature.source_feature_ref}"
            ),
            "source_digest": feature.source_feature_digest,
            "input_role": "current_evidence",
            "status": "admitted",
            "resource_kind": "gis",
            "reason": "test_current_world_input",
        }],
    )
    store = WorldModelKGStore(
        "session-identity",
        "测试村",
        catalog,
        artifact_root=str(tmp_path),
    )
    base_snapshot = store.snapshot_contract()
    entity = store.find_entities(limit=1)[0]
    entity_ref = entity["entity_ref"]
    entity_count = len(store.find_entities(limit=100))
    representation_count = len(base_snapshot.representation_refs)
    geometry_count = len(
        list(store.g.subjects(RDF.type, GEO.Geometry))
    )

    l1_ref = _artifact_ref({}, schema_id="L1ObservationSnapshot", label="l1")
    base_ref = _artifact_ref(
        base_snapshot,
        schema_id="SessionWorldModelSnapshot",
        label="base-world",
    )
    observation = EvidenceObservation(
        observation_id="work-item:road",
        work_item_ref="work-item:road",
        source_mention_refs=["source-mention:transport:1"],
        dimension_keys=["transport"],
        scope_refs=["scope:village-a"],
        mention="村道",
        normalized_name="村道",
        spatial_hint="沿村道",
    )
    second_observation = EvidenceObservation(
        observation_id="work-item:road-nearby",
        work_item_ref="work-item:road-nearby",
        source_mention_refs=["source-mention:transport:2"],
        dimension_keys=["transport"],
        scope_refs=["scope:village-a"],
        mention="村道附近",
        normalized_name="村道附近",
        spatial_hint="村道附近",
        relation_mentions=["near:work-item:road"],
    )
    observation_snapshot = EvidenceObservationSnapshot(
        observations=[observation, second_observation],
        provenance_refs=[l1_ref.digest],
        parent_digest=l1_ref.digest,
    )
    observation_ref = _artifact_ref(
        observation_snapshot,
        schema_id="EvidenceObservationSnapshot",
        label="observations",
    )
    binding = GroundedEntityBinding(
        binding_id="binding:road",
        mention_ref="work-item:road",
        canonical_entity_ref=entity_ref,
        candidate_entity_refs=[entity_ref],
        observation_refs=["work-item:road"],
        status="feature_set",
        evidence_refs=["evidence:local-road"],
    )
    second_binding = GroundedEntityBinding(
        binding_id="binding:road-nearby",
        mention_ref="work-item:road-nearby",
        observation_refs=["work-item:road-nearby"],
        status="not_applicable",
        evidence_refs=["evidence:local-road-nearby"],
        relation_evidence_refs=["relation:near:road"],
        location_expression_ref="location-expression:road-nearby",
        location_expression_status="bound",
        spatial_relation="near",
        anchor_entity_refs=[entity_ref],
        anchor_work_item_refs=["work-item:road"],
    )
    binding_snapshot = GroundedEntityBindingSnapshot(
        bindings=[binding, second_binding],
        observation_snapshot_ref=observation_ref.digest,
        parent_digest=observation_ref.digest,
        source_world_model_snapshot_ref=base_snapshot.snapshot_ref,
        source_world_model_snapshot_digest=base_snapshot.graph_digest,
        status_counts={"resolved": 1, "not_applicable": 1},
    )
    binding_ref = _artifact_ref(
        binding_snapshot,
        schema_id="GroundedEntityBindingSnapshot",
        label="bindings",
    )
    envelope = IdentityBindingCommitEnvelope(
        run_id="run-identity",
        branch_id="main",
        l1_snapshot_artifact_ref=l1_ref,
        source_world_model_artifact_ref=base_ref,
        source_world_model_snapshot=base_snapshot,
        observation_artifact_ref=observation_ref,
        observation_snapshot=observation_snapshot,
        binding_artifact_ref=binding_ref,
        binding_snapshot=binding_snapshot,
    )

    committed = store.commit_identity_bindings(envelope)
    assert committed.status == "committed"
    assert committed.committed is True
    assert committed.world_model_version == base_snapshot.version + 1
    assert committed.world_model_snapshot_digest != base_snapshot.graph_digest
    assert len(store.find_entities(limit=100)) == entity_count
    assert len(store.snapshot_contract().representation_refs) == representation_count
    assert len(list(store.g.subjects(RDF.type, GEO.Geometry))) == geometry_count

    rows = store.find_identity_bindings(
        dimension_ref="transport",
        work_item_ref="work-item:road",
        scope_ref="scope:village-a",
        limit=999,
    )
    assert len(rows) == 1
    assert rows[0]["identity_status"] == "resolved"
    assert rows[0]["canonical_entity_ref"] == entity_ref
    assert rows[0]["source_mention_refs"] == [
        "source-mention:transport:1"
    ]
    assert rows[0]["spatial_hint"] == "沿村道"
    relative_rows = store.find_identity_bindings(
        entity_ref=entity_ref,
        work_item_ref="work-item:road-nearby",
        limit=8,
    )
    assert len(relative_rows) == 1
    assert relative_rows[0]["identity_status"] == "not_applicable"
    assert relative_rows[0]["location_expression_status"] == "bound"
    assert relative_rows[0]["spatial_relation"] == "near"
    assert relative_rows[0]["anchor_entity_refs"] == [entity_ref]
    assert relative_rows[0]["anchor_work_item_refs"] == [
        "work-item:road"
    ]
    with pytest.raises(ValueError, match="explicit dependency selector"):
        store.find_identity_bindings(limit=1)

    replay = store.commit_identity_bindings(envelope)
    assert replay.status == "noop"
    assert replay.world_model_version == committed.world_model_version
    assert replay.world_model_snapshot_digest == (
        committed.world_model_snapshot_digest
    )

    request = IdentityBindingProjectionRequest(
        consumer_stage="L2",
        consumer_dimension_key="transport_strategy",
        dependency_dimension_keys=("transport",),
        world_model_snapshot_ref=committed.world_model_snapshot_ref,
        world_model_snapshot_digest=committed.world_model_snapshot_digest,
        requested_page_size=1,
    )
    first_page = store.query_identity_binding_page(request)
    assert first_page.matched_total == 2
    assert first_page.emitted_count == 1
    assert first_page.truncated is True
    assert first_page.next_cursor
    second_page = store.query_identity_binding_page(
        request.model_copy(update={"cursor": first_page.next_cursor})
    )
    assert second_page.emitted_count == 1
    assert second_page.truncated is False
    assert (
        first_page.rows[0].binding_ref
        != second_page.rows[0].binding_ref
    )

    context = type("Context", (), {
        "ports": type("Ports", (), {"world_model": store})(),
    })()
    rendered = ContextProjectionRuntime.build_identity_binding_table(
        context,
        request.model_copy(update={
            "work_item_refs": ("work-item:road",),
            "requested_page_size": 24,
        }),
    )
    assert rendered.page.matched_total == 1
    assert rendered.rendered_count == 1
    assert "| binding_ref | work_item_ref |" in rendered.table
    assert "沿村道" in rendered.table
    assert "binding:road-nearby" not in rendered.table
    relative_rendered = (
        ContextProjectionRuntime.build_identity_binding_table(
            context,
            request.model_copy(update={
                "work_item_refs": ("work-item:road-nearby",),
                "requested_page_size": 24,
            }),
        )
    )
    assert relative_rendered.page.matched_total == 1
    assert relative_rendered.page.rows[0].canonical_entity_ref == ""
    assert relative_rendered.page.rows[0].anchor_labels == ("村道",)
    assert "relation=near" in relative_rendered.table
    assert "anchor_work_items=work-item:road" in relative_rendered.table
    with pytest.raises(ValueError, match="digest mismatch"):
        store.query_identity_binding_page(
            request.model_copy(update={
                "world_model_snapshot_digest": "sha256:" + "0" * 64,
            })
        )
