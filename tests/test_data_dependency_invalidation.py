from __future__ import annotations

from app.contracts.data.source_contracts import (
    DataCapability,
    DataResourceCatalogSnapshot,
    SourceDataset,
    SourceFeature,
    SpatialRepresentation,
)
from app.modules.data.invalidation import build_data_dependency_graph, plan_data_change_set


def _catalog(feature_digest: str = "feature-a") -> DataResourceCatalogSnapshot:
    dataset = SourceDataset(dataset_ref="dataset:jintian", name="Jintian", digest="dataset-1")
    feature = SourceFeature(
        dataset_ref=dataset.dataset_ref,
        source_feature_ref="landuse:1",
        source_feature_digest=feature_digest,
        geometry_kind="polygon",
        geometry={"type": "Polygon", "coordinates": []},
        normalized_geometry={"type": "Polygon", "coordinates": []},
        raw_attributes={"input_role": "current_evidence"},
    )
    representation = SpatialRepresentation(
        representation_ref="representation:landuse:1",
        resource_ref="resource:dataset:jintian:landuse:1",
        geometry_ref="landuse:1",
        geometry_kind="polygon",
        dataset_ref=dataset.dataset_ref,
        source_feature_ref=feature.source_feature_ref,
        source_snapshot_ref="snapshot-1",
        content_digest=feature_digest,
        status="available",
    )
    capability = DataCapability(
        capability_ref="capability:landuse:1",
        resource_ref="resource:dataset:jintian:landuse:1",
        operation="spatial_query",
        geometry_kind="polygon",
        source_snapshot_ref="snapshot-1",
        content_digest=feature_digest,
    )
    return DataResourceCatalogSnapshot(
        snapshot_id="snapshot-1",
        dataset=dataset,
        datasets=(dataset,),
        features=(feature,),
        representations=(representation,),
        capabilities=(capability,),
        admission_decisions=(),
        admission_policy_version="current-world-admission-v1",
    )


def test_changed_feature_invalidates_transitive_consumer_subgraphs():
    old = build_data_dependency_graph(_catalog())
    new = build_data_dependency_graph(_catalog("feature-b"))

    change_set = plan_data_change_set(old, new)

    assert "data:source:dataset:jintian:landuse:1" in change_set.changed_nodes
    assert "data:source:dataset:jintian:landuse:1" in change_set.affected_data_nodes
    assert all(node.startswith("data:") for node in change_set.affected_data_nodes)
    assert change_set.conservative is False


def test_unchanged_graph_has_no_invalidation():
    graph = build_data_dependency_graph(_catalog())
    change_set = plan_data_change_set(graph, graph)
    assert change_set.changed_nodes == ()
    assert change_set.affected_data_nodes == ()


def test_missing_previous_graph_is_conservative():
    graph = build_data_dependency_graph(_catalog())
    change_set = plan_data_change_set(None, graph)
    assert change_set.conservative is True
    assert change_set.affected_data_nodes
