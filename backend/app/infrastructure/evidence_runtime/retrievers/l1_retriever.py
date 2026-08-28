"""Typed L1 fact projection for the unified evidence bundle."""

from __future__ import annotations

from typing import Any, Iterable

from app.contracts.evidence.evidence_contracts import EvidenceFact, EvidenceSource
from app.workflow.validation.l1_fact_catalog import is_canonical_l1_fact_id


RETRIEVER_VERSION = "l1-v2"
_FACT_LIMIT = 12
_SPATIAL_DIMENSIONS = frozenset({"location", "spatial"})
_SPATIAL_SEMANTIC_TYPES = frozenset({
    "axis", "building", "bridge", "drainage", "facility", "infrastructure",
    "landmark", "landuse", "parcel", "place", "point", "polygon", "project",
    "road", "settlement", "utility", "village", "water", "waterbody", "zone",
})
_SPATIAL_ATTRIBUTE_KEYS = frozenset({
    "location", "spatial_hint", "normalized_name", "source_feature_id",
    "source_feature_ids", "village", "settlement", "natural_village",
})


def _text(value: Any) -> str:
    return str(value or "").strip()


def _is_spatial_record(record: Any) -> bool:
    """Use the L1 typed contract to classify spatial facts.

    L1 facts are not report prose.  A fact can belong to a professional
    dimension such as ``public_service`` or ``socio_economic`` and still be a
    spatial object fact.  The classification therefore uses typed semantic
    fields and source identity, never sentence keywords.
    """
    dimension = _text(getattr(record, "dimension_key", "")).casefold()
    semantic_type = _text(getattr(record, "semantic_type", "")).casefold()
    if dimension in _SPATIAL_DIMENSIONS or semantic_type in _SPATIAL_SEMANTIC_TYPES:
        return True
    if any(_text(value) for value in (getattr(record, "source_feature_ids", None) or [])):
        return True
    attributes = getattr(record, "attributes", None)
    if not isinstance(attributes, dict):
        return False
    return any(
        _text(key).casefold() in _SPATIAL_ATTRIBUTE_KEYS and _text(value)
        for key, value in attributes.items()
    )


def _record_matches(record: Any, query: str, required_facts: Iterable[str]) -> bool:
    values = [
        _text(getattr(record, "statement", "")),
        _text(getattr(record, "dimension_key", "")),
        _text(getattr(record, "subject_scope", "")),
        _text(getattr(record, "semantic_type", "")),
        _text(getattr(record, "counting_basis", "")),
        *[
            f"{_text(key)} {_text(value)}"
            for key, value in (getattr(record, "attributes", None) or {}).items()
        ],
    ]
    haystack = " ".join(value for value in values if value).casefold()
    raw_terms = [_text(value).casefold() for value in [query, *required_facts] if _text(value)]
    terms = list(raw_terms)
    for value in raw_terms:
        if len(value) > 2:
            terms.extend(value[index : index + 2] for index in range(len(value) - 1))
    return not terms or any(term in haystack for term in terms)


def _record_to_evidence(record: Any, snapshot_ref: str) -> tuple[EvidenceFact, EvidenceSource]:
    dimension_key = _text(getattr(record, "dimension_key", ""))
    spatial_record = _is_spatial_record(record)
    source_refs = [
        _text(value)
        for value in (getattr(record, "source_refs", None) or [])
        if _text(value)
    ]
    fact_kind = _text(getattr(record, "fact_kind", ""))
    fields = {
        "fact_id": _text(getattr(record, "fact_id", "")),
        "fact_kind": fact_kind,
        "origin_fact_kind": fact_kind,
        "dimension_key": _text(getattr(record, "dimension_key", "")),
        "subject_scope": _text(getattr(record, "subject_scope", "")),
        "semantic_type": _text(getattr(record, "semantic_type", "")),
        "counting_basis": _text(getattr(record, "counting_basis", "")),
        "source_snapshot_ref": _text(getattr(record, "source_snapshot_ref", "")) or snapshot_ref,
        "source_feature_ids": ",".join(
            _text(value)
            for value in (getattr(record, "source_feature_ids", None) or [])
            if _text(value)
        ),
        "evidence_role": "location_binding" if spatial_record else "planning_background",
        "source_kind": "l1_typed_fact",
    }
    fields.update(
        {
            _text(key): _text(value)
            for key, value in (getattr(record, "attributes", None) or {}).items()
            if _text(key) and _text(value)
        }
    )
    confidence = max(0.0, min(1.0, float(getattr(record, "confidence", 0.0) or 0.0)))
    fact = EvidenceFact(
        statement=_text(getattr(record, "statement", "")),
        confidence=confidence,
        source_refs=source_refs,
        fact_type="l1_fact",
        fields=fields,
        evidence_span=_text(getattr(record, "source_span", ""))[:400],
        source_locator=source_refs[0] if source_refs else _text(getattr(record, "fact_id", "")),
        support_relation="l1_typed_fact",
        status="verified" if confidence >= 0.8 else "needs_review",
        evidence_role="location_binding" if spatial_record else "planning_background",
        source_kind="l1_typed_fact",
        spatial_granularity="feature" if spatial_record else "none",
        planning_use="grounding" if spatial_record else "context",
    )
    source = EvidenceSource(
        # This row is a projection of the authoritative L1 snapshot.  Its
        # upstream fact_kind is retained in the EvidenceFact fields; exposing
        # it as ``gis_layer`` or ``kg`` here would incorrectly grant the L1
        # projection direct geometry/topology authority.
        source_type="l1",
        reference=_text(getattr(record, "fact_id", "")),
        confidence=confidence,
    )
    return fact, source


def retrieve_from_l1_context(
    context: Any,
    *,
    query: str = "",
    required_facts: Iterable[str] = (),
    dimension_key: str = "",
    strict_dimension: bool = False,
    allow_cross_dimension: bool = False,
) -> tuple[list[EvidenceFact], list[EvidenceSource]]:
    """Project bounded typed L1 facts without resolving geometry.

    Spatial L1 facts are cross-dimension evidence.  A hazard address in a
    natural-environment report can be the only semantic anchor for a village
    requested by a traffic or land-use worker.  ``dimension_key`` identifies
    the business owner, not a hard source partition.  For project-wide and
    gap-resolution requests, ``allow_cross_dimension`` also exposes matching
    non-spatial L1 facts from another dimension.  Geometry and topology
    authority remains at Bundle/KG.
    """
    facts: list[EvidenceFact] = []
    sources: list[EvidenceSource] = []
    snapshot_ref = _text(getattr(context, "l1_snapshot_ref", ""))
    typed_records = list(getattr(context, "l1_fact_records", None) or [])
    for record in typed_records:
        # The L1 snapshot is authoritative, but only its canonical fact
        # namespace is selectable downstream.  Do not leak legacy or missing
        # IDs into the unified evidence plane where an LLM could copy them.
        if not is_canonical_l1_fact_id(getattr(record, "fact_id", "")):
            continue
        spatial_record = _is_spatial_record(record)
        dimension = _text(getattr(record, "dimension_key", ""))
        if strict_dimension and dimension_key and dimension and dimension != dimension_key:
            continue
        if (
            not strict_dimension
            and not allow_cross_dimension
            and not spatial_record
            and dimension_key
            and dimension
            and dimension != dimension_key
        ):
            continue
        if not _record_matches(record, query, required_facts):
            continue
        projected, source = _record_to_evidence(record, snapshot_ref)
        if not projected.statement or not source.reference:
            continue
        facts.append(projected)
        sources.append(source)
        if len(facts) >= _FACT_LIMIT:
            return facts, sources

    return facts, sources


__all__ = ["RETRIEVER_VERSION", "retrieve_from_l1_context"]
