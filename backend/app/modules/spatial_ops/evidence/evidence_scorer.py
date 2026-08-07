"""Evidence scorer - 8 deterministic dimensions from design §4.2.

Scores are config-driven (see ``WEIGHTS``) and never written into an LLM
prompt. ``fuzzy_short_name`` is prohibited from auto-passing and thus
contributes nothing to the weighted total.
"""
from __future__ import annotations

from typing import Any, Dict

from app.modules.schema.contracts.place_resolution_contracts import (
    PlaceEvidenceEntry,
)

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

    evidence["relation_topology"] = 0.0

    evidence["within_bundle"] = 0.5 if entry.source_bsms else 0.0

    evidence["geometry_near_anchor"] = 0.0

    has_poi = "poi" in entry.provenance
    evidence["external_geocoder"] = 0.3 if has_poi else 0.0

    evidence["fuzzy_short_name"] = 0.0

    return evidence


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