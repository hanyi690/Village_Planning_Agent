"""KG query subpackage — data queries (SPARQL) + semantic queries (memory).

Two categories:
  tools.py  — Structured SPARQL queries for EXECUTE/MIP (data-oriented)
  semantic.py — LLM-friendly semantic queries (human-readable descriptions)
"""
from .tools import QUERY_TEMPLATES, query_kg, TOOL_META
from .semantic import (
    get_entity_context, get_entity_relations,
    get_parcel_semantic_context, get_village_semantic_summary,
    TOOL_META_SEMANTIC,
)

__all__ = [
    "QUERY_TEMPLATES", "query_kg", "TOOL_META",
    "get_entity_context", "get_entity_relations",
    "get_parcel_semantic_context", "get_village_semantic_summary",
    "TOOL_META_SEMANTIC",
]