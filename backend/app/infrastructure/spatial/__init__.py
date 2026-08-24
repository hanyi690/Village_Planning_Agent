"""Deterministic spatial query adapters."""

from app.infrastructure.spatial.postgis_executor import (
    POSTGIS_SPATIAL_QUERY_SCHEMA_SQL,
    PostGISSpatialQueryExecutor,
    SpatialQueryPlan,
    compile_spatial_query,
)

__all__ = [
    "POSTGIS_SPATIAL_QUERY_SCHEMA_SQL",
    "PostGISSpatialQueryExecutor",
    "SpatialQueryPlan",
    "compile_spatial_query",
]
