"""Planning Knowledge Graph module.

Independently-scoped KG for village planning context and constraints.
Consumed by GIS tools (kg.py, parse_tools.py), PARSE Agent, and future
EXECUTE_OPS Agent — not confined to the GIS subpackage.

Query categories:
  - Data queries: SPARQL templates (query_kg / QUERY_TEMPLATES)
  - Semantic queries: LLM-friendly context (get_entity_context, etc.)
"""
from .builder import PlanningKG, KGInputParcels
from .queries import (
    QUERY_TEMPLATES, query_kg, TOOL_META,
    get_entity_context, get_entity_relations,
    get_parcel_semantic_context, get_village_semantic_summary,
    TOOL_META_SEMANTIC,
)
from .ontology import PLN, GEO, EntityTypes, Relations
from .manager import KGManager, CacheKey, compute_layer1_cache_key, get_kg_manager
from .memory import SemanticMemoryStore, EntityAnnotation, RelationAnnotation, get_semantic_memory

__all__ = [
    "PlanningKG", "KGInputParcels",
    "QUERY_TEMPLATES", "query_kg", "TOOL_META",
    "get_entity_context", "get_entity_relations",
    "get_parcel_semantic_context", "get_village_semantic_summary",
    "TOOL_META_SEMANTIC",
    "PLN", "GEO", "EntityTypes", "Relations",
    "KGManager", "CacheKey", "compute_layer1_cache_key", "get_kg_manager",
    "SemanticMemoryStore", "EntityAnnotation", "RelationAnnotation", "get_semantic_memory",
]