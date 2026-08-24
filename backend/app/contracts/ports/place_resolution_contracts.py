"""Place resolution contracts - typed output of the evidence-based place resolver.

Defines the contract between the place resolver and downstream consumers
(SpatialResolver.resolve_spec). The resolver produces a PlaceResolutionResult
from candidate PlaceResolutionCandidate objects scored across eight evidence
dimensions defined in EvidenceScore.

See docs/design/02_EVIDENCE_AND_GROUNDING.md for the current place-grounding boundary.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel

from app.contracts.artifacts.contract_meta import ContractMeta


class PlaceResolutionCandidate(BaseModel):
    """A single candidate entity produced by the place resolver."""

    entity_ref: str
    entity_type: str
    role: str = ""
    canonical_name: str
    aliases: list[str] = []
    geometry_ref: str | None = None
    feature_bsm: str | None = None
    source_feature_id: str | None = None
    source_layer: str | None = None
    source_bsm: str | None = None
    anchor_bsms: list[str] = []
    related_parcel_bsms: list[str] = []
    source_bsms: list[str] = []
    score: float
    evidence_refs: list[str] = []
    relation_refs: list[str] = []
    l1_fact_refs: list[str] = []
    l1_snapshot_ref: str = ""
    bundle_snapshot_digest: str = ""
    evidence: dict[str, float] = {}


@dataclass
class EvidenceScore:
    """Eight evidence dimensions and their configured weights.

    Scoring is a deterministic, config-driven process; ``fuzzy_short_name``
    is prohibited from auto-passing (must never trigger automatic resolution).
    """

    DIMENSIONS: list[str] = field(
        default_factory=lambda: [
            "exact_canonical_alias",
            "l1_fact_exact",
            "entity_type_role",
            "relation_topology",
            "within_bundle",
            "geometry_near_anchor",
            "external_geocoder",
            "fuzzy_short_name",
        ]
    )
    WEIGHTS: dict[str, str] = field(
        default_factory=lambda: {
            "exact_canonical_alias": "high",
            "l1_fact_exact": "high",
            "entity_type_role": "medium",
            "relation_topology": "medium",
            "within_bundle": "medium",
            "geometry_near_anchor": "medium",
            "external_geocoder": "low",
            "fuzzy_short_name": "prohibited",
        }
    )

    def total(self, candidate: PlaceResolutionCandidate) -> float:
        """Sum the per-dimension scores for a candidate.

        Prohibited dimensions contribute nothing to the total.
        """
        return sum(
            score
            for dim, score in candidate.evidence.items()
            if self.WEIGHTS.get(dim) != "prohibited"
        )


class PlaceResolutionResult(ContractMeta):
    """Root contract emitted by the place resolver for a single mention."""

    mention: str
    normalized_name: str
    status: Literal["resolved", "ambiguous", "unresolved"]
    selected_entity_ref: str | None = None
    candidates: list[PlaceResolutionCandidate] = []
    evidence_refs: list[str] = []
    query_trace: list[dict[str, Any]] = []
    unresolved_reason: str | None = None


class PlaceEvidenceEntry(BaseModel):
    """An index entry consumed by the resolver for candidate generation."""

    canonical_name: str
    aliases: list[str] = []
    entity_refs: list[str] = []
    entity_types: list[str] = []
    role: str = "unknown"
    feature_bsm: str | None = None
    source_feature_id: str | None = None
    source_layer: str | None = None
    source_bsm: str | None = None
    anchor_bsms: list[str] = []
    related_parcel_bsms: list[str] = []
    source_bsms: list[str] = []
    geometry_ref: str | None = None
    provenance: list[str] = []
    confidence: float = 0.0
    relation_refs: list[str] = []
    l1_fact_refs: list[str] = []
    l1_snapshot_ref: str = ""
    bundle_snapshot_digest: str = ""


__all__ = [
    "PlaceResolutionCandidate",
    "EvidenceScore",
    "PlaceResolutionResult",
    "PlaceEvidenceEntry",
]
