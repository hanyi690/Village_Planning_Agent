"""Deterministic Evidence Runtime result fusion and deduplication."""

from __future__ import annotations

from app.contracts.evidence.evidence_contracts import EvidenceFact, EvidenceSource

from .provenance import source_key


def fuse_facts(facts: list[EvidenceFact]) -> list[EvidenceFact]:
    seen: set[tuple[str, tuple[str, ...], str]] = set()
    result: list[EvidenceFact] = []
    for fact in facts:
        key = (
            " ".join(fact.statement.split()).casefold(),
            tuple(sorted(fact.source_refs)),
            fact.fact_type,
        )
        if key not in seen:
            seen.add(key)
            result.append(fact)
    return result


def fuse_sources(sources: list[EvidenceSource]) -> list[EvidenceSource]:
    seen: set[tuple[str, str, str, str]] = set()
    result: list[EvidenceSource] = []
    for source in sources:
        key = source_key(source)
        if key not in seen:
            seen.add(key)
            result.append(source)
    return result


__all__ = ["fuse_facts", "fuse_sources"]
