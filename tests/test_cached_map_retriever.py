from types import SimpleNamespace

from app.contracts.evidence.external_observation_contracts import (
    ExternalObservation,
    ExternalObservationSnapshot,
)
from app.contracts.evidence.requirement_contracts import EvidenceRequirement
from app.infrastructure.evidence_runtime.retrievers.cached_map_retriever import (
    retrieve_from_cached_map,
)
from app.infrastructure.evidence_runtime.v2_catalog import (
    _candidate_identity_projection,
    _external_query,
    _external_spatial_support,
    _match,
)
from app.modules.evidence.requirements import requirements_from_l1


class _Context:
    def __init__(self, snapshot):
        self.external_observation_snapshot = snapshot


def test_cached_map_projection_is_advisory_and_lineage_bearing():
    snapshot = ExternalObservationSnapshot(
        snapshot_id="snap-1",
        observations=[
            ExternalObservation(
                observation_id="obs-1",
                provider="amap",
                stage="02_l1_place_names",
                scope_bucket="project_local",
                observed_name="金田村卫生室",
                aliases=["卫生室"],
                observed_type="facility",
                location_wgs84=(113.1, 23.1),
                coordinate_contract="WGS84 direct",
                coordinate_source_crs="EPSG:4326",
                coordinate_target_crs="CRS84",
                coordinate_trust_status="verified_direct",
                spatial_evidence_role="feature_location",
                raw_response_ref="cache://amap/raw/1",
                source_record_ref="amap:record:1",
            )
        ],
    )
    facts, sources, trace = retrieve_from_cached_map(
        _Context(snapshot), query="卫生室", entity_scope=["facilities"]
    )
    assert len(facts) == len(sources) == 1
    assert facts[0].fact_type == "external_map_observation"
    assert facts[0].planning_use == "grounding"
    assert facts[0].spatial_refs == ["external-observation:obs-1"]
    assert sources[0].authority == "advisory"
    assert sources[0].snapshot_ref == "snap-1"
    assert trace["cache_only"] is True


def test_cached_map_unverified_coordinate_keeps_name_only_evidence():
    snapshot = ExternalObservationSnapshot(
        snapshot_id="snap-unverified",
        observations=[
            ExternalObservation(
                observation_id="external-observation:unknown-1",
                provider="tianditu",
                stage="02_l1_place_names",
                observed_name="金田村",
                location_wgs84=(113.1, 23.1),
                coordinate_trust_status="unverified",
            )
        ],
    )
    facts, _, _ = retrieve_from_cached_map(_Context(snapshot), query="金田村")
    assert facts[0].spatial_refs == []
    assert facts[0].fields["coordinate_trust_status"] == "unverified"
    assert facts[0].evidence_role == "name_observation"
    assert facts[0].planning_use == "context"


def test_cached_map_requires_explicit_feature_location_role():
    snapshot = ExternalObservationSnapshot(
        snapshot_id="snap-default-role",
        observations=[
            ExternalObservation(
                observation_id="trusted-but-unclassified",
                provider="custom",
                stage="02_l1_place_names",
                observed_name="古茶亭",
                location_wgs84=(116.04, 24.82),
                coordinate_contract="WGS84 direct",
                coordinate_source_crs="WGS84",
                coordinate_target_crs="WGS84",
                coordinate_trust_status="verified_direct",
            )
        ],
    )
    facts, _, _ = retrieve_from_cached_map(_Context(snapshot), query="古茶亭")
    assert facts[0].fields["spatial_evidence_role"] == "name_only"
    assert facts[0].spatial_refs == []
    assert facts[0].evidence_role == "name_observation"


def test_cached_map_projection_respects_scope_without_http():
    snapshot = ExternalObservationSnapshot(
        snapshot_id="snap-2",
        observations=[
            ExternalObservation(
                observation_id="road-1",
                provider="tianditu",
                stage="01_admin_scope",
                scope_bucket="project_local",
                observed_name="村道",
                observed_type="road",
            ),
            ExternalObservation(
                observation_id="water-1",
                provider="tianditu",
                stage="01_admin_scope",
                scope_bucket="project_local",
                observed_name="池塘",
                observed_type="waterbody",
            ),
        ],
    )
    facts, _, _ = retrieve_from_cached_map(
        _Context(snapshot), query="", entity_scope=["roads"]
    )
    assert [fact.fields["observation_id"] for fact in facts] == ["road-1"]


def test_v2_external_support_separates_co_located_entity_clusters():
    context = SimpleNamespace()
    snapshot = SimpleNamespace(digest="snapshot-1")
    feature = SimpleNamespace(
        dataset_ref="dataset-1",
        source_feature_ref="feature-1",
        geometry_kind="point",
        normalized_geometry={
            "type": "Point",
            "coordinates": [116.04, 24.82],
        },
    )
    representations = {
        ("dataset-1", "feature-1"): [
            SimpleNamespace(normalized_crs="EPSG:4326", crs="")
        ]
    }
    observations = [
        {
            "observation_ref": "external-observation:committee",
            "location_wgs84": (116.04, 24.82),
            "observed_name": "金田村委会",
            "aliases": [],
            "observed_type": "facility",
            "cluster_id": "cluster-committee",
        },
        {
            "observation_ref": "external-observation:service",
            "location_wgs84": (116.04, 24.82),
            "observed_name": "退役军人服务站",
            "aliases": [],
            "observed_type": "facility",
            "cluster_id": "cluster-service",
        },
    ]
    support = _external_spatial_support(
        context,
        snapshot,
        [feature],
        representations,
        {
            ("dataset-1", "feature-1"): [
                {
                    "canonical_name": "金田村委会",
                    "aliases": [],
                    "concept_types": ["facility"],
                }
            ]
        },
        observations,
    )[("dataset-1", "feature-1")]
    assert support["observation_refs"] == [
        "external-observation:committee"
    ]
    assert support["cluster_ids"] == ["cluster-committee"]
    assert support["cluster_count"] == 1
    assert support["nearby_cluster_count"] == 2
    assert support["semantic_match"] is True


def test_v2_external_support_keeps_spatial_only_identity_ambiguous():
    context = SimpleNamespace()
    snapshot = SimpleNamespace(digest="snapshot-2")
    feature = SimpleNamespace(
        dataset_ref="dataset-1",
        source_feature_ref="feature-1",
        geometry_kind="point",
        normalized_geometry={
            "type": "Point",
            "coordinates": [116.04, 24.82],
        },
    )
    support = _external_spatial_support(
        context,
        snapshot,
        [feature],
        {
            ("dataset-1", "feature-1"): [
                SimpleNamespace(normalized_crs="WGS84", crs="")
            ]
        },
        {},
        [
            {
                "observation_ref": "external-observation:a",
                "location_wgs84": (116.04, 24.82),
                "observed_name": "甲设施",
                "aliases": [],
                "observed_type": "facility",
                "cluster_id": "cluster-a",
            },
            {
                "observation_ref": "external-observation:b",
                "location_wgs84": (116.04, 24.82),
                "observed_name": "乙设施",
                "aliases": [],
                "observed_type": "facility",
                "cluster_id": "cluster-b",
            },
        ],
    )[("dataset-1", "feature-1")]
    assert support["cluster_count"] == 2
    assert support["semantic_match"] is False


def test_v2_identity_statement_is_a_filter_not_project_wide_fallback():
    requirement = EvidenceRequirement(
        requirement_id="identity-1",
        statement="金田村委会",
        kind="identity",
        evidence_role="location_binding",
    )
    matching = SimpleNamespace(
        source_feature_ref="feature-1",
        raw_attributes={"name": "金田村委会"},
        geometry_kind="point",
    )
    unrelated = SimpleNamespace(
        source_feature_ref="feature-2",
        raw_attributes={"name": "退役军人服务站"},
        geometry_kind="point",
    )
    assert _match(matching, requirement) is True
    assert _match(unrelated, requirement) is False
    assert _external_query((requirement,)) == "金田村委会"


def test_v2_external_cluster_blocks_to_bounded_nearest_candidates():
    context = SimpleNamespace()
    snapshot = SimpleNamespace(digest="snapshot-cap")
    features = [
        SimpleNamespace(
            dataset_ref="dataset-1",
            source_feature_ref=f"feature-{index:02d}",
            geometry_kind="point",
            normalized_geometry={
                "type": "Point",
                "coordinates": [116.04 + index * 0.000001, 24.82],
            },
        )
        for index in range(12)
    ]
    representations = {
        ("dataset-1", feature.source_feature_ref): [
            SimpleNamespace(normalized_crs="EPSG:4326", crs="")
        ]
        for feature in features
    }
    support = _external_spatial_support(
        context,
        snapshot,
        features,
        representations,
        {},
        [
            {
                "observation_ref": "external-observation:one-cluster",
                "location_wgs84": (116.04, 24.82),
                "observed_name": "金田村委会",
                "aliases": [],
                "observed_type": "facility",
                "cluster_id": "cluster-one",
            }
        ],
    )
    assert len(support) == 8
    assert ("dataset-1", "feature-00") in support
    assert ("dataset-1", "feature-11") not in support


def test_l1_location_identity_requirement_consumes_cache_as_advisory_support():
    snapshot = SimpleNamespace(
        artifact_id="l1-snapshot-1",
        context_fingerprint="context-1",
        evidence_gaps=[],
        location_mentions=[
            SimpleNamespace(
                normalized_name="金田村委会",
                mention="金田村委会",
                role="facility",
                resolution_state="needs_retrieval",
            )
        ],
    )
    requirements = requirements_from_l1(snapshot)

    assert len(requirements) == 1
    requirement = requirements[0]
    assert requirement.evidence_role == "l1_location_identity"
    assert "external_map_cache" in requirement.source_families
    assert requirement.metadata["selection_cardinality"] == "one"
    assert requirement.metadata["external_geometry_authority"] == "advisory_only"


def test_identity_projection_collapses_multiple_features_of_one_world_entity():
    features = [
        SimpleNamespace(dataset_ref="roads", source_feature_ref="segment-a"),
        SimpleNamespace(dataset_ref="roads", source_feature_ref="segment-b"),
    ]
    projection = _candidate_identity_projection(
        features,
        {
            ("roads", "segment-a"): [{"entity_ref": "entity:main-road"}],
            ("roads", "segment-b"): [{"entity_ref": "entity:main-road"}],
        },
    )

    assert projection["group_count"] == 1
    assert projection["entity_refs"] == ["entity:main-road"]
    assert projection["mode"] == "world_entity"
    assert projection["entity_backed_feature_count"] == 2


def test_identity_projection_keeps_distinct_world_entities_ambiguous():
    features = [
        SimpleNamespace(dataset_ref="places", source_feature_ref="point-a"),
        SimpleNamespace(dataset_ref="places", source_feature_ref="polygon-b"),
    ]
    projection = _candidate_identity_projection(
        features,
        {
            ("places", "point-a"): [{"entity_ref": "entity:clinic-a"}],
            ("places", "polygon-b"): [{"entity_ref": "entity:clinic-b"}],
        },
    )

    assert projection["group_count"] == 2
    assert projection["entity_refs"] == ["entity:clinic-a", "entity:clinic-b"]
    assert projection["mode"] == "world_entity"
