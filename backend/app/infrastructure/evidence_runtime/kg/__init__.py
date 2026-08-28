"""Semantic KG evidence containers (indexes, never spatial truth)."""

from .base_facts import BaseFacts
from .derived_relations import DerivedRelations
from .reverse_relation_index import ReverseRelationIndex

__all__ = ["BaseFacts", "DerivedRelations", "ReverseRelationIndex"]
