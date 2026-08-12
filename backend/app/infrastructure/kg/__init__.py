"""PlanningKG module - Pre-computed Spatial Materialized Knowledge Graph."""
from .builder import PlanningKG, KGBuilder, KGInputParcels
from .ontology import PLN, GEO, EntityTypes, Relations, SemanticPredicates, GeoPredicates
from .manager import KGManager, CacheKey, compute_layer1_cache_key, get_kg_manager
from .memory import SemanticMemoryStore, EntityAnnotation, RelationAnnotation, get_semantic_memory
from .interface import (
    KGSessionSnapshot,
    open_kg_session,
    require_session_kg,
    query_session_sparql,
    query_session_template,
    close_kg_session,
)
from .queries import (
    QUERY_TEMPLATES, query_kg, TOOL_META,
    get_entity_context, get_entity_relations,
    get_parcel_semantic_context, get_village_semantic_summary,
    get_entity_by_bsm, get_parcels_by_planning_zone,
    get_l4_derived_from_l1, get_village_constraint_coverage,
    get_entity_semantics, get_village_cognition,
    get_parcels_semantic_list, get_parcel_detail_semantic,
    get_parcel_neighbors_semantic, get_facilities_semantic_list,
    get_designated_zones_semantic, get_road_network_semantic,
    get_layer_group_semantics,
    analysis_queries, parse_queries, execute_queries, shared_queries,
    DualPayload, TokenBudget, TopKSampler,
    get_effective_land_use, get_effective_area_ha,
    get_plan_changes, get_planned_parcels_in_zone,
    check_constraint_violations, compare_versions,
    resolve_candidates,
)

__all__ = [
    "PlanningKG", "KGBuilder", "KGInputParcels",
    "PLN", "GEO", "EntityTypes", "Relations", "SemanticPredicates", "GeoPredicates",
    "KGManager", "CacheKey", "compute_layer1_cache_key", "get_kg_manager",
    "SemanticMemoryStore", "EntityAnnotation", "RelationAnnotation", "get_semantic_memory",
    "QUERY_TEMPLATES", "query_kg", "TOOL_META",
    "get_entity_context", "get_entity_relations",
    "get_parcel_semantic_context", "get_village_semantic_summary",
    "get_entity_by_bsm", "get_parcels_by_planning_zone",
    "get_l4_derived_from_l1", "get_village_constraint_coverage",
    "get_entity_semantics", "get_village_cognition",
    "get_parcels_semantic_list", "get_parcel_detail_semantic",
    "get_parcel_neighbors_semantic", "get_facilities_semantic_list",
    "get_designated_zones_semantic", "get_road_network_semantic",
    "get_layer_group_semantics",
    "analysis_queries", "parse_queries", "execute_queries", "shared_queries",
    "DualPayload", "TokenBudget", "TopKSampler",
    "get_effective_land_use", "get_effective_area_ha",
    "get_plan_changes", "get_planned_parcels_in_zone",
    "check_constraint_violations", "compare_versions",
    "resolve_candidates",
    # Stable integration boundary (stage-0 surface)
    "KGSessionSnapshot",
    "open_kg_session",
    "require_session_kg",
    "query_session_sparql",
    "query_session_template",
    "close_kg_session",
]
