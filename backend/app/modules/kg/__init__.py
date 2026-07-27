"""Planning Knowledge Graph module.

Independently-scoped KG for village planning context and constraints.
Consumed by GIS tools (kg.py, parse_tools.py), PARSE Agent, and future
EXECUTE_OPS Agent - not confined to the GIS subpackage.

Query categories:
  - SPARQL templates + instance methods: sparql.py (query_kg / QUERY_TEMPLATES / get_constraint_coverage)
  - Semantic queries: semantic.py (get_entity_context, etc.)
"""
from .builder import PlanningKG, KGInputParcels
from .queries import (
    QUERY_TEMPLATES, query_kg, TOOL_META,
    get_constraint_coverage,
    get_entity_context, get_entity_relations,
    get_parcel_semantic_context, get_village_semantic_summary,
    get_entity_by_bsm, get_parcels_by_planning_zone,
    get_l4_derived_from_l1, get_village_constraint_coverage,
    TOOL_META_SEMANTIC,
)
from .ontology import PLN, GEO, EntityTypes, Relations
from .manager import KGManager, CacheKey, compute_layer1_cache_key, get_kg_manager
from .memory import SemanticMemoryStore, EntityAnnotation, RelationAnnotation, get_semantic_memory

__all__ = [
    "PlanningKG", "KGInputParcels",
    "QUERY_TEMPLATES", "query_kg", "TOOL_META", "get_constraint_coverage",
    "get_entity_context", "get_entity_relations",
    "get_parcel_semantic_context", "get_village_semantic_summary",
    "get_entity_by_bsm", "get_parcels_by_planning_zone",
    "get_l4_derived_from_l1", "get_village_constraint_coverage",
    "TOOL_META_SEMANTIC",
    "PLN", "GEO", "EntityTypes", "Relations",
    "KGManager", "CacheKey", "compute_layer1_cache_key", "get_kg_manager",
    "SemanticMemoryStore", "EntityAnnotation", "RelationAnnotation", "get_semantic_memory",
]
