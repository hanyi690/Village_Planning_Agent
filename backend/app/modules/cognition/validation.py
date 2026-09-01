"""Validation helpers for cognition snapshots."""

from __future__ import annotations

from app.contracts.cognition.decision import SourceSemanticMappingSnapshot


def accepted_schema_decisions(snapshot: SourceSemanticMappingSnapshot) -> list:
    return [item for item in snapshot.decisions if item.status == "accepted"]


def has_only_closed_set_decisions(snapshot: SourceSemanticMappingSnapshot) -> bool:
    return not any(item.status == "rejected" for item in snapshot.decisions)


__all__ = ["accepted_schema_decisions", "has_only_closed_set_decisions"]
