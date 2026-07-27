"""KG query subpackage - SPARQL templates + instance methods + semantic queries.

Two files:
  sparql.py    - SPARQL template registry (QUERY_TEMPLATES) + query_kg() + instance methods (QueryMixin)
  semantic.py  - LLM-friendly semantic queries (human-readable descriptions)
"""
from .sparql import (
    QUERY_TEMPLATES, query_kg, TOOL_META,
    query, get_adjacency_map,
    get_parcel_count, get_triple_count, serialize, to_turtle, from_turtle,
    get_parcels_within_distance_of_entity, get_adjacent_parcels_with_length,
    get_connected_parcels, get_parcels_by_bsm_list, validate_intent,
    _is_in_protected_zone, get_constraint_coverage,
)
from .semantic import (
    get_entity_context, get_entity_relations,
    get_parcel_semantic_context, get_village_semantic_summary,
    get_entity_by_bsm, get_parcels_by_planning_zone,
    get_l4_derived_from_l1, get_village_constraint_coverage,
    TOOL_META_SEMANTIC,
)

__all__ = [
    # SPARQL templates + query_kg
    "QUERY_TEMPLATES", "query_kg", "TOOL_META",
    # Instance methods (also mixed into PlanningKG via QueryMixin)
    "query", "get_adjacency_map",
    "get_parcel_count", "get_triple_count", "serialize", "to_turtle", "from_turtle",
    "get_parcels_within_distance_of_entity", "get_adjacent_parcels_with_length",
    "get_connected_parcels", "get_parcels_by_bsm_list", "validate_intent",
    "get_constraint_coverage",
    # Semantic queries
    "get_entity_context", "get_entity_relations",
    "get_parcel_semantic_context", "get_village_semantic_summary",
    "get_entity_by_bsm", "get_parcels_by_planning_zone",
    "get_l4_derived_from_l1", "get_village_constraint_coverage",
    "TOOL_META_SEMANTIC",
]
