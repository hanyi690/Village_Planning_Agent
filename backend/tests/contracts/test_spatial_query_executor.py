import pytest

from app.contracts.spatial.query_ast import (
    AttributeFilter,
    DatasetRef,
    DistancePredicate,
    EntityRef,
    SpatialQuery,
)
from app.infrastructure.spatial.postgis_executor import compile_spatial_query


def _query() -> SpatialQuery:
    return SpatialQuery(
        query_id="spatial-query-1",
        dataset=DatasetRef(
            dataset_id="village-bundle",
            snapshot_id="snapshot-1",
            layer_id="facilities",
        ),
        crs="EPSG:4490",
        entity_refs=(EntityRef(kind="place_name", name="金田村"),),
        predicates=(
            DistancePredicate(
                kind="distance_lte",
                reference=EntityRef(kind="layer_group", name="main_road"),
                threshold=500,
                unit="m",
                metric="planar",
            ),
        ),
        filters=(AttributeFilter(field="status", operator="eq", value="current"),),
        limit=10,
    )


def test_spatial_query_compiles_to_snapshot_bound_parameterized_sql() -> None:
    plan = compile_spatial_query(_query())

    assert plan.fingerprint == _query().fingerprint
    assert "spatial_features" in plan.sql
    assert "e.snapshot_id = :snapshot_id" in plan.sql
    assert "ST_DWithin" in plan.sql
    assert plan.params["snapshot_id"] == "snapshot-1"
    assert plan.params["filter_value_0"] == "current"
    assert "金田村" not in plan.sql
    assert "SELECT *" not in plan.sql


def test_spatial_query_rejects_unsupported_network_execution_without_network_metric() -> None:
    query = SpatialQuery(
        query_id="spatial-query-network",
        dataset=DatasetRef(
            dataset_id="village-bundle",
            snapshot_id="snapshot-1",
            layer_id="facilities",
        ),
        crs="EPSG:4490",
        predicates=(
            DistancePredicate(
                kind="distance_lte",
                reference=EntityRef(kind="layer_group", name="main_road"),
                threshold=5,
                unit="minutes",
                metric="network",
            ),
        ),
    )

    with pytest.raises(ValueError, match="network distance"):
        compile_spatial_query(query)
