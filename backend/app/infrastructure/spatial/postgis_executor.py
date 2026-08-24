"""Whitelist compiler and PostGIS executor for :class:`SpatialQuery`.

The compiler is intentionally independent from SQLAlchemy execution so the
query boundary can be tested without a database.  User-controlled values are
always bound parameters; predicate/operator/column choices come only from the
closed AST model and fixed maps in this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.contracts.spatial.query_ast import (
    AttributeFilter,
    DistancePredicate,
    EntityRef,
    RelationPredicate,
    SpatialQuery,
    TopologyPredicate,
)


@dataclass(frozen=True)
class SpatialQueryPlan:
    sql: str
    params: dict[str, Any]
    fingerprint: str


_FILTER_OPERATORS = {
    "eq": "=",
    "neq": "<>",
    "gte": ">=",
    "lte": "<=",
    "gt": ">",
    "lt": "<",
}
_RELATION_FUNCTIONS = {
    "within": "ST_Within(e.geometry, ref.geometry)",
    "intersects": "ST_Intersects(e.geometry, ref.geometry)",
    "contains": "ST_Contains(e.geometry, ref.geometry)",
    "touches": "ST_Touches(e.geometry, ref.geometry)",
}
_TOPOLOGY_PREDICATES = {
    "connected_to": "connected_to",
    "adjacent_to": "adjacent_to",
    "upstream_of": "upstream_of",
    "downstream_of": "downstream_of",
}


def _entity_condition(
    reference: EntityRef,
    *,
    prefix: str,
    table_alias: str = "e",
) -> tuple[str, dict[str, Any]]:
    clauses: list[str] = []
    params: dict[str, Any] = {}
    if reference.entity_id.strip():
        key = f"{prefix}_entity_id"
        clauses.append(f"{table_alias}.entity_ref = :{key}")
        params[key] = reference.entity_id.strip()
    if reference.name.strip():
        key = f"{prefix}_name"
        clauses.append(f"{table_alias}.canonical_name = :{key}")
        params[key] = reference.name.strip()
    if reference.aliases:
        for index, alias in enumerate(reference.aliases):
            key = f"{prefix}_alias_{index}"
            clauses.append(f"{table_alias}.aliases ? :{key}")
            params[key] = alias
    if reference.kind == "bsm" and reference.name.strip():
        key = f"{prefix}_bsm"
        clauses.append(f"{table_alias}.feature_bsm = :{key}")
        params[key] = reference.name.strip()
    if not clauses:
        raise ValueError("spatial entity reference must contain a name or entity_id")
    return "(" + " OR ".join(clauses) + ")", params


def _compile_filter(item: AttributeFilter, index: int) -> tuple[str, dict[str, Any]]:
    params: dict[str, Any] = {f"filter_field_{index}": item.field, f"filter_value_{index}": item.value}
    if item.operator == "in":
        values = item.value if isinstance(item.value, (list, tuple, set)) else [item.value]
        params[f"filter_values_{index}"] = list(values)
        return (
            f"e.properties ->> :filter_field_{index} = ANY(:filter_values_{index})",
            params,
        )
    operator = _FILTER_OPERATORS.get(item.operator)
    if operator is None:
        if item.operator == "contains":
            return (
                f"e.properties ->> :filter_field_{index} ILIKE '%' || :filter_value_{index} || '%'",
                params,
            )
        raise ValueError(f"unsupported attribute filter operator: {item.operator}")
    return (
        f"e.properties ->> :filter_field_{index} {operator} CAST(:filter_value_{index} AS TEXT)",
        params,
    )


def _compile_relation(item: RelationPredicate, index: int) -> tuple[str, dict[str, Any]]:
    if item.kind == "nearest":
        raise ValueError("nearest requires an explicit distance/sort plan and is not executable alone")
    predicate = _RELATION_FUNCTIONS[item.kind]
    ref_condition, ref_params = _entity_condition(item.reference, prefix=f"relation_{index}", table_alias="ref")
    return (
        "EXISTS (SELECT 1 FROM spatial_features ref "
        "WHERE ref.dataset_id = e.dataset_id "
        "AND ref.snapshot_id = e.snapshot_id "
        "AND " + ref_condition + " AND " + predicate + ")",
        ref_params,
    )


def _compile_distance(item: DistancePredicate, index: int) -> tuple[str, dict[str, Any]]:
    ref_condition, ref_params = _entity_condition(item.reference, prefix=f"distance_{index}", table_alias="ref")
    key = f"distance_threshold_{index}"
    params = {**ref_params, key: item.threshold}
    if item.metric == "network":
        raise ValueError("network distance requires a precomputed network metric relation")
    return (
        "EXISTS (SELECT 1 FROM spatial_features ref "
        "WHERE ref.dataset_id = e.dataset_id "
        "AND ref.snapshot_id = e.snapshot_id "
        "AND " + ref_condition +
        f" AND ST_DWithin(e.geometry, ref.geometry, :{key}))",
        params,
    )


def _compile_topology(item: TopologyPredicate, index: int) -> tuple[str, dict[str, Any]]:
    ref_condition, ref_params = _entity_condition(item.reference, prefix=f"topology_{index}", table_alias="ref")
    key = f"topology_predicate_{index}"
    return (
        "EXISTS (SELECT 1 FROM spatial_relations rel "
        "JOIN spatial_features ref ON ref.dataset_id = rel.dataset_id "
        "AND ref.snapshot_id = rel.snapshot_id "
        "AND ref.entity_ref = rel.object_ref "
        "WHERE rel.dataset_id = e.dataset_id "
        "AND rel.snapshot_id = e.snapshot_id "
        "AND rel.subject_ref = e.entity_ref "
        f"AND rel.predicate = :{key} AND {ref_condition})",
        {**ref_params, key: _TOPOLOGY_PREDICATES[item.kind]},
    )


def compile_spatial_query(query: SpatialQuery) -> SpatialQueryPlan:
    """Compile a validated AST into a deterministic, parameterized SQL plan."""

    if not query.execution_ready:
        raise ValueError("spatial query is not execution-ready")
    params: dict[str, Any] = {
        "dataset_id": query.dataset.dataset_id,
        "snapshot_id": query.dataset.snapshot_id,
        "layer_id": query.dataset.layer_id,
    }
    where = [
        "e.dataset_id = :dataset_id",
        "e.snapshot_id = :snapshot_id",
        "e.layer_id = :layer_id",
        "e.crs = :query_crs",
    ]
    params["query_crs"] = query.crs

    entity_clauses: list[str] = []
    for index, reference in enumerate(query.entity_refs):
        clause, values = _entity_condition(reference, prefix=f"entity_{index}")
        entity_clauses.append(clause)
        params.update(values)
    if entity_clauses:
        where.append("(" + " OR ".join(entity_clauses) + ")")

    for index, item in enumerate(query.filters):
        clause, values = _compile_filter(item, index)
        where.append(clause)
        params.update(values)

    for index, item in enumerate(query.predicates):
        if isinstance(item, RelationPredicate):
            clause, values = _compile_relation(item, index)
        elif isinstance(item, DistancePredicate):
            clause, values = _compile_distance(item, index)
        elif isinstance(item, TopologyPredicate):
            clause, values = _compile_topology(item, index)
        else:  # pragma: no cover - discriminated union prevents this path
            raise ValueError(f"unsupported spatial predicate: {type(item).__name__}")
        where.append(clause)
        params.update(values)

    if query.aggregate is not None:
        operation = query.aggregate.operation.upper()
        if operation == "COUNT":
            select = "COUNT(*) AS aggregate_value"
        elif operation in {"AREA", "LENGTH"}:
            select = f"ST_{operation}(e.geometry) AS aggregate_value"
        else:
            field_key = "aggregate_field"
            params[field_key] = query.aggregate.field
            select = f"{operation}(CAST(e.properties ->> :{field_key} AS DOUBLE PRECISION)) AS aggregate_value"
    else:
        select = (
            "e.entity_ref, e.canonical_name, e.entity_type, e.feature_bsm, "
            "e.source_feature_id, e.layer_id, e.snapshot_id, e.crs, "
            "ST_AsText(e.geometry) AS geometry_wkt, e.properties"
        )

    order = ""
    if query.sort:
        clauses = []
        for index, item in enumerate(query.sort):
            key = f"sort_field_{index}"
            params[key] = item.field
            clauses.append(
                f"e.properties ->> :{key} {'ASC' if item.direction == 'asc' else 'DESC'}"
            )
        order = " ORDER BY " + ", ".join(clauses)

    sql = (
        f"SELECT {select} FROM spatial_features e WHERE "
        + " AND ".join(where)
        + order
        + " LIMIT :limit"
    )
    params["limit"] = query.limit
    return SpatialQueryPlan(sql=sql, params=params, fingerprint=query.fingerprint)


class PostGISSpatialQueryExecutor:
    """Connection-scoped executor for the canonical AST boundary."""

    def __init__(self, connection: Any) -> None:
        if connection is None:
            raise ValueError("PostGISSpatialQueryExecutor requires a connection")
        self.connection = connection

    def execute(self, query: SpatialQuery) -> list[dict[str, Any]]:
        plan = compile_spatial_query(query)
        from sqlalchemy import text

        rows = self.connection.execute(text(plan.sql), plan.params)
        return [dict(getattr(row, "_mapping", row)) for row in rows]


POSTGIS_SPATIAL_QUERY_SCHEMA_SQL: tuple[str, ...] = (
    "CREATE EXTENSION IF NOT EXISTS postgis",
    """
    CREATE TABLE IF NOT EXISTS spatial_features (
        dataset_id TEXT NOT NULL,
        snapshot_id TEXT NOT NULL,
        layer_id TEXT NOT NULL,
        entity_ref TEXT NOT NULL,
        canonical_name TEXT NOT NULL DEFAULT '',
        entity_type TEXT NOT NULL DEFAULT '',
        aliases JSONB NOT NULL DEFAULT '[]'::jsonb,
        feature_bsm TEXT,
        source_feature_id TEXT,
        crs TEXT NOT NULL,
        geometry geometry(Geometry) NOT NULL,
        properties JSONB NOT NULL DEFAULT '{}'::jsonb,
        PRIMARY KEY (dataset_id, snapshot_id, layer_id, entity_ref)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_spatial_features_snapshot_geom ON spatial_features USING GIST (geometry)",
    """
    CREATE TABLE IF NOT EXISTS spatial_relations (
        dataset_id TEXT NOT NULL,
        snapshot_id TEXT NOT NULL,
        relation_id TEXT NOT NULL,
        subject_ref TEXT NOT NULL,
        predicate TEXT NOT NULL,
        object_ref TEXT NOT NULL,
        properties JSONB NOT NULL DEFAULT '{}'::jsonb,
        PRIMARY KEY (dataset_id, snapshot_id, relation_id)
    )
    """,
)


__all__ = [
    "POSTGIS_SPATIAL_QUERY_SCHEMA_SQL",
    "PostGISSpatialQueryExecutor",
    "SpatialQueryPlan",
    "compile_spatial_query",
]
