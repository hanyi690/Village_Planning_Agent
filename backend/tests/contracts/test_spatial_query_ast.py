import pytest
from pydantic import ValidationError

from app.contracts.spatial.query_ast import (
    AttributeFilter,
    DatasetRef,
    DistancePredicate,
    EntityRef,
    RelationPredicate,
    SpatialQuery,
    SortSpec,
    TopologyPredicate,
)


def _query() -> SpatialQuery:
    return SpatialQuery(
        query_id="query-1",
        dataset=DatasetRef(
            dataset_id="village-bundle",
            snapshot_id="snapshot-2026-08",
            layer_id="roads",
        ),
        crs="EPSG:4490",
        entity_refs=(
            EntityRef(kind="place_name", name="金田村", scope=("village",)),
        ),
        predicates=(
            RelationPredicate(
                kind="within",
                reference=EntityRef(kind="place_name", name="金田村"),
            ),
            DistancePredicate(
                kind="distance_lte",
                reference=EntityRef(kind="layer_group", name="main_road"),
                threshold=500,
                unit="m",
                metric="planar",
            ),
            TopologyPredicate(
                kind="connected_to",
                reference=EntityRef(kind="entity_type", name="settlement"),
            ),
        ),
        filters=(AttributeFilter(field="status", operator="eq", value="current"),),
        sort=(SortSpec(field="distance_m", direction="asc"),),
        limit=20,
    )


def test_spatial_query_is_closed_set_and_fingerprint_is_stable() -> None:
    first = _query()
    second = _query()

    assert first.fingerprint == second.fingerprint
    assert first.execution_ready is True
    assert first.dataset.snapshot_id == "snapshot-2026-08"
    assert "sql" not in first.model_dump()


def test_spatial_query_requires_snapshot_crs_and_bounded_entities() -> None:
    with pytest.raises(ValidationError):
        DatasetRef(dataset_id="bundle", snapshot_id="", layer_id="roads")

    with pytest.raises(ValidationError):
        SpatialQuery(
            query_id="query-1",
            dataset=DatasetRef(dataset_id="bundle", snapshot_id="snapshot-1", layer_id="roads"),
            crs="",
        )

    with pytest.raises(ValidationError):
        EntityRef(kind="place_name", name="", coordinates=[116.0, 24.0])


def test_spatial_query_rejects_free_sql_and_invalid_distance() -> None:
    with pytest.raises(ValidationError):
        SpatialQuery(
            query_id="query-1",
            dataset=DatasetRef(dataset_id="bundle", snapshot_id="snapshot-1", layer_id="roads"),
            crs="EPSG:4326",
            sql="SELECT * FROM roads",
        )

    with pytest.raises(ValidationError):
        DistancePredicate(
            kind="distance_lte",
            reference=EntityRef(kind="layer_group", name="roads"),
            threshold=0,
            unit="m",
            metric="planar",
        )


def test_spatial_query_rejects_unbounded_limit() -> None:
    with pytest.raises(ValidationError):
        SpatialQuery(
            query_id="query-1",
            dataset=DatasetRef(dataset_id="bundle", snapshot_id="snapshot-1", layer_id="roads"),
            crs="EPSG:4326",
            limit=0,
        )
