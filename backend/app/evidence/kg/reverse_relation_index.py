"""Reverse relation index; never silently picks the first candidate."""

from __future__ import annotations

from typing import Iterable

from app.contracts.workflow.repair import RelationEvidence


class ReverseRelationIndex:
    """Index (subject, predicate) -> all object_refs; ambiguity surfaces to caller."""

    def __init__(self, relations: Iterable[RelationEvidence] | None = None) -> None:
        self._index: dict[tuple[str, str], list[str]] = {}
        for relation in relations or []:
            self.add(relation)

    def add(self, relation: RelationEvidence) -> None:
        key = (relation.subject_ref, relation.predicate)
        object_refs = self._index.setdefault(key, [])
        if relation.object_ref not in object_refs:
            object_refs.append(relation.object_ref)

    def lookup(self, subject: str, predicate: str) -> list[str]:
        """Return the full list of object refs; an empty list means unresolved."""
        return list(self._index.get((subject, predicate), []))


__all__ = ["ReverseRelationIndex"]
