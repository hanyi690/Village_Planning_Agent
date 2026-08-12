"""Data ownership boundary for session snapshots and ingestion."""

from .model.snapshot import CollectionSnapshot, SessionDataSnapshot

__all__ = ["CollectionSnapshot", "SessionDataSnapshot"]
