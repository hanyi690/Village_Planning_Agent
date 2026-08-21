"""Evidence scorer - 8 deterministic dimensions from design §4.2.

Scores are config-driven (see ``WEIGHTS``) and never written into an LLM
prompt. ``fuzzy_short_name`` is prohibited from auto-passing and thus
contributes nothing to the weighted total.
"""
from __future__ import annotations

from typing import Any, Dict

from app.contracts.ports.place_resolution_contracts import (
    PlaceEvidenceEntry,
)
from app.infrastructure.logging import get_logger

logger = get_logger(__name__)

#: Per-dimension weights; "high"/"medium"/"low" map to numeric weights,
#: "prohibited" contributes nothing to the total.
WEIGHTS: Dict[str, float] = {
    "exact_canonical_alias": 1.0,
    "l1_fact_exact": 1.0,
    "entity_type_role": 0.5,
    "relation_topology": 0.5,
    "within_bundle": 0.5,
    "geometry_near_anchor": 0.5,
    "external_geocoder": 0.3,
    "fuzzy_short_name": 0.0,
}

def score_candidate(
    mention: str,
    entry: PlaceEvidenceEntry,
    role: str = "unknown",
    hints: str = "",
    context: Any = None,
) -> Dict[str, float]:
    """Score an index entry across the eight evidence dimensions.

    Args:
        mention: Raw mention to resolve.
        entry: Candidate ``PlaceEvidenceEntry`` from the index.
        role: Expected role (village/facility/road/... or "unknown").
        hints: Optional topology/relationship hints (unused for now).
        context: Optional ``PlanningContext`` (reserved for geometry/topology).

    Returns:
        ``{dimension: score}`` dict. ``fuzzy_short_name`` is set to
        ``0.0`` when the candidate was reached only by fuzzy/substring match;
        it is omitted otherwise.
    """
    evidence: Dict[str, float] = {}
    norm = _normalize(mention)
    aliases = {_normalize(a) for a in entry.aliases if a}

    exact = norm == _normalize(entry.canonical_name) or norm in aliases
    evidence["exact_canonical_alias"] = 1.0 if exact else 0.0

    has_l1 = "l1_fact" in entry.provenance
    evidence["l1_fact_exact"] = 1.0 if (has_l1 and exact) else 0.0

    role_match = role == "unknown" or entry.role == role
    evidence["entity_type_role"] = 0.5 if role_match else 0.0

    evidence["relation_topology"] = _relation_topology_score(
        entry, hints=hints, context=context
    )

    evidence["within_bundle"] = 0.5 if entry.source_bsms else 0.0

    evidence["geometry_near_anchor"] = _geometry_near_anchor_score(
        entry,
        hints=hints,
        context=context,
    )

    has_poi = "poi" in entry.provenance
    evidence["external_geocoder"] = 0.3 if has_poi else 0.0

    evidence["fuzzy_short_name"] = 0.0

    return evidence


def _relation_topology_score(
    entry: "PlaceEvidenceEntry",
    *,
    hints: str = "",
    context: Any = None,
) -> float:
    """Real topology check (design §4.2): candidate's precomputed KG relations
    must connect it to an entity named in the mention hints.

    Fallback for legacy/context-less scoring keeps the historical "has
    relation_refs" signal at reduced weight; the authoritative path uses the KG
    graph via ``app.spatial.grounding.topology``.
    """
    kg = getattr(context, "kg", None) if context is not None else None
    graph = None
    if kg is not None:
        graph = getattr(kg, "g", None) or getattr(kg, "graph", None) or kg
    entity_uri = ""
    if entry.entity_refs:
        entity_uri = entry.entity_refs[0]
    if hints and graph is not None and entity_uri:
        try:
            from app.spatial.grounding.topology import topology_evidence_for

            hits = topology_evidence_for(
                graph,
                entity_uri,
                hints=hints,
                relation_refs=list(getattr(entry, "relation_refs", None) or []),
            )
            if hits:
                return 0.5
        except Exception as exc:  # noqa: BLE001
            logger.warning("[evidence_scorer] topology check failed: %s", exc)
    return 0.3 if getattr(entry, "relation_refs", None) else 0.0


def _geometry_near_anchor_score(
    entry: "PlaceEvidenceEntry",
    *,
    hints: str = "",
    context: Any = None,
) -> float:
    """Score a real Bundle parcel overlap with a named village anchor.

    The matched village names and parcel sets come from the session gazetteer;
    no text heuristic manufactures a boundary.  Point features participate via
    their Bundle-derived ``related_parcel_bsms``.  A future PostGIS adapter can
    replace this overlap check with indexed distance without changing the
    evidence dimension exposed to the LLM.
    """

    if context is None or not str(hints or "").strip():
        return 0.0
    candidate_bsms = {
        str(value).strip()
        for value in [
            *(getattr(entry, "anchor_bsms", None) or []),
            *(getattr(entry, "related_parcel_bsms", None) or []),
            *(getattr(entry, "source_bsms", None) or []),
        ]
        if str(value).strip()
    }
    if not candidate_bsms:
        return 0.0
    folded_hints = str(hints).casefold()
    gazetteer = getattr(context, "gazetteer", None)
    for scope in getattr(gazetteer, "entries", None) or []:
        names = [
            str(getattr(scope, "name", "") or "").strip(),
            *[
                str(value).strip()
                for value in (getattr(scope, "aliases", None) or [])
                if str(value).strip()
            ],
        ]
        if not any(name.casefold() in folded_hints for name in names if name):
            continue
        scope_bsms = {
            str(value).strip()
            for value in (getattr(scope, "bsms", None) or [])
            if str(value).strip()
        }
        if scope_bsms.intersection(candidate_bsms):
            return 0.5
    return 0.0


def total(evidence: Dict[str, float]) -> float:
    """Weighted sum of an evidence dict; prohibited dims contribute nothing."""
    return sum(
        score
        for dim, score in evidence.items()
        if WEIGHTS.get(dim, 0.0) > 0.0  # see _PROHIBITED_DIMENSIONS
    )


def _normalize(name: str) -> str:
    """Normalize a place name: strip whitespace and village suffixes."""
    if not name:
        return ""
    cleaned = name.strip().lower()
    for suffix in ("自然村", "村"):
        if cleaned.endswith(suffix):
            cleaned = cleaned[: -len(suffix)].strip()
            break
    return cleaned


__all__ = ["score_candidate", "WEIGHTS", "total"]
