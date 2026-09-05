"""Immutable DATA catalog products and provider observation infrastructure."""

from __future__ import annotations

from .collection_registry import CollectionRecord, CollectionRegistry
from .session_resource_catalog import load_session_data_catalog

__all__ = [
    "CollectionRecord",
    "CollectionRegistry",
    "load_session_data_catalog",
]
