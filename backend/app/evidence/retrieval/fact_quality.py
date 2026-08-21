"""Provenance and comparability checks for unified evidence facts.

This module deliberately does not infer business meaning from prose.  Numeric
comparison is allowed only when the producer supplied typed value metadata and
the facts share a comparable scope, snapshot, unit, and counting basis.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from app.contracts.evidence.evidence_contracts import (
    EvidenceBundle,
    EvidenceConflict,
    EvidenceFact,
)


_QUANTITATIVE_BASES = {
    "source_feature",
    "business_object",
    "topology_edge",
    "derived_metric",
}


def fact_ref(fact: EvidenceFact) -> str:
    """Return a stable reference even for legacy facts without ``fact_id``."""
    explicit = str(fact.fields.get("fact_id") or "").strip()
    if explicit:
        return explicit
    raw = json.dumps(
        {
            "statement": " ".join(fact.statement.split()),
            "source_refs": sorted(str(value) for value in fact.source_refs),
            "fact_type": fact.fact_type,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return "evidence:fact:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def _field(fact: EvidenceFact, name: str) -> str:
    return str(fact.fields.get(name) or "").strip()


def _number(fact: EvidenceFact) -> Decimal | None:
    raw = _field(fact, "value")
    if not raw:
        return None
    try:
        return Decimal(raw)
    except (InvalidOperation, ValueError):
        return None


def _is_quantitative(fact: EvidenceFact) -> bool:
    basis = _field(fact, "counting_basis")
    return _number(fact) is not None and basis in _QUANTITATIVE_BASES


def _has_source_feature_lineage(fact: EvidenceFact) -> bool:
    collection = _field(fact, "source_collection_key")
    snapshot = _field(fact, "source_snapshot_ref")
    feature_ids = [
        value.strip()
        for value in _field(fact, "source_feature_ids").split(",")
        if value.strip()
    ]
    digest = _field(fact, "source_feature_digest")
    return bool(collection and snapshot and (feature_ids or digest))


def _metadata(fact: EvidenceFact) -> tuple[str, str, str, str, str]:
    return (
        _field(fact, "subject_scope"),
        _field(fact, "source_snapshot_ref"),
        _field(fact, "unit"),
        _field(fact, "counting_basis"),
        _field(fact, "source_collection_key"),
    )


@dataclass(frozen=True)
class FactQualityReport:
    facts: list[EvidenceFact]
    conflicts: list[EvidenceConflict]
    unverified_refs: tuple[str, ...] = ()


def evaluate_fact_quality(facts: list[EvidenceFact]) -> FactQualityReport:
    """Annotate facts and return only evidence relationships, never a winner."""
    prepared: list[EvidenceFact] = []
    unverified: list[str] = []
    for fact in facts:
        ref = fact_ref(fact)
        flags = list(dict.fromkeys(str(value) for value in fact.support_relations if value))
        status = fact.status
        if _is_quantitative(fact):
            basis = _field(fact, "counting_basis")
            if basis == "source_feature" and not _has_source_feature_lineage(fact):
                if "unverified" not in flags:
                    flags.append("unverified")
                status = "needs_review"
                unverified.append(ref)
        prepared.append(
            fact.model_copy(
                update={
                    "support_relations": flags,
                    "related_fact_refs": list(fact.related_fact_refs),
                    "status": status,
                }
            )
        )

    groups: dict[tuple[str, str], list[int]] = {}
    for index, fact in enumerate(prepared):
        if not _is_quantitative(fact):
            continue
        scope, snapshot, unit, basis, collection = _metadata(fact)
        if not scope or not snapshot or not unit or not basis:
            continue
        if basis == "source_feature" and not _has_source_feature_lineage(fact):
            continue
        groups.setdefault((scope, unit), []).append(index)

    conflicts: list[EvidenceConflict] = []
    for key, indexes in groups.items():
        scope, unit = key
        for left_pos, left_index in enumerate(indexes):
            left = prepared[left_index]
            left_meta = _metadata(left)
            left_value = _number(left)
            for right_index in indexes[left_pos + 1 :]:
                right = prepared[right_index]
                right_meta = _metadata(right)
                right_value = _number(right)
                relation = ""
                reason = ""
                if left_meta[3] != right_meta[3]:
                    relation = "different_counting_basis"
                    reason = "same subject scope/unit but different counting bases"
                elif left_meta[1] != right_meta[1]:
                    relation = "different_counting_basis"
                    reason = "same subject/unit/basis but different source snapshots"
                elif left_meta[4] and right_meta[4] and left_meta[4] != right_meta[4]:
                    relation = "different_counting_basis"
                    reason = "same subject/snapshot/unit but different source collections"
                elif left_value is not None and right_value is not None:
                    relation = "supports" if left_value == right_value else "contradicts"
                    reason = (
                        "same subject scope, snapshot, unit, and counting basis"
                    )
                if not relation:
                    continue
                left_ref = fact_ref(left)
                right_ref = fact_ref(right)
                for index, other_ref in ((left_index, right_ref), (right_index, left_ref)):
                    current = prepared[index]
                    relations = list(dict.fromkeys([*current.support_relations, relation]))
                    related = list(dict.fromkeys([*current.related_fact_refs, other_ref]))
                    prepared[index] = current.model_copy(
                        update={
                            "support_relations": relations,
                            "related_fact_refs": related,
                            "status": (
                                "needs_review"
                                if relation in {"contradicts", "different_counting_basis"}
                                else current.status
                            ),
                        }
                    )
                conflicts.append(
                    EvidenceConflict(
                        relation=relation,
                        fact_refs=[left_ref, right_ref],
                        reason=reason,
                        subject_scope=scope,
                        counting_bases=list(dict.fromkeys([left_meta[3], right_meta[3]])),
                    )
                )

    return FactQualityReport(
        facts=prepared,
        conflicts=conflicts,
        unverified_refs=tuple(dict.fromkeys(unverified)),
    )


def apply_fact_quality(bundle: EvidenceBundle) -> EvidenceBundle:
    """Return a bundle with quality annotations and explicit audit conflicts."""
    report = evaluate_fact_quality(list(bundle.facts))
    unresolved = list(bundle.unresolved)
    for ref in report.unverified_refs:
        marker = f"unverified_quantitative_fact:{ref}"
        if marker not in unresolved:
            unresolved.append(marker)
    return bundle.model_copy(
        update={
            "facts": report.facts,
            "conflicts": report.conflicts,
            "unresolved": unresolved,
        }
    )


__all__ = [
    "FactQualityReport",
    "apply_fact_quality",
    "evaluate_fact_quality",
    "fact_ref",
]
