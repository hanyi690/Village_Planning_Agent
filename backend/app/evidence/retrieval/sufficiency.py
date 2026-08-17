"""Deterministic evidence sufficiency decisions for gate requests."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from app.contracts.evidence.evidence_contracts import ExplorationRequest, ExplorationResult


class SufficiencyStatus(StrEnum):
    SUFFICIENT = "sufficient"
    MISSING_FACT = "missing_fact"
    AMBIGUOUS = "ambiguous"
    SOURCE_UNAVAILABLE = "source_unavailable"
    INSUFFICIENT_GEOMETRY = "insufficient_geometry"


@dataclass(frozen=True)
class SufficiencyDecision:
    status: SufficiencyStatus
    missing_facts: tuple[str, ...] = ()
    ambiguous_facts: tuple[str, ...] = ()
    unavailable_sources: tuple[str, ...] = ()
    next_request: ExplorationRequest | None = None
    reason: str = ""

    @property
    def terminal(self) -> bool:
        return self.status in {
            SufficiencyStatus.SUFFICIENT,
            SufficiencyStatus.SOURCE_UNAVAILABLE,
            SufficiencyStatus.INSUFFICIENT_GEOMETRY,
        }


def _fact_text(result: ExplorationResult) -> list[str]:
    return [fact.statement.strip().lower() for fact in result.evidence_bundle.facts if fact.statement.strip()]


def _covered(required: str, facts: list[str]) -> bool:
    tokens = [token for token in required.lower().split() if len(token) > 1]
    if not tokens:
        return True
    return any(all(token in fact for token in tokens) for fact in facts)


def evaluate_sufficiency(
    request: ExplorationRequest,
    response: ExplorationResult,
) -> SufficiencyDecision:
    """Classify evidence without treating ``facts != empty`` as success."""
    facts = _fact_text(response)
    required = tuple(dict.fromkeys([*request.required_facts, *request.questions]))
    missing = tuple(item for item in required if not _covered(item, facts))
    sources = response.evidence_bundle.sources
    if not sources:
        return SufficiencyDecision(
            status=SufficiencyStatus.SOURCE_UNAVAILABLE,
            missing_facts=missing,
            unavailable_sources=("all",),
            next_request=request,
            reason="no retriever returned a source",
        )

    if missing:
        def _anchor(value: str) -> str:
            parts = value.lower().split()
            if len(parts) > 1:
                return parts[0]
            return value.lower()[:2]

        ambiguous = tuple(item for item in missing if sum(_anchor(item) in fact for fact in facts) > 1)
        if ambiguous:
            return SufficiencyDecision(
                status=SufficiencyStatus.AMBIGUOUS,
                missing_facts=missing,
                ambiguous_facts=ambiguous,
                next_request=request.model_copy(update={"questions": list(ambiguous)}),
                reason="multiple candidate facts need disambiguation",
            )
        if request.entity_scope and not any(fact.spatial_refs for fact in response.evidence_bundle.facts):
            return SufficiencyDecision(
                status=SufficiencyStatus.INSUFFICIENT_GEOMETRY,
                missing_facts=missing,
                next_request=request.model_copy(update={"query_purpose": "gap_resolution"}),
                reason="facts exist but carry no spatial references for the requested scope",
            )
        return SufficiencyDecision(
            status=SufficiencyStatus.MISSING_FACT,
            missing_facts=missing,
            next_request=request.model_copy(update={"required_facts": list(missing), "query_purpose": "gap_resolution"}),
            reason="required facts are not covered by retrieved statements",
        )

    if request.entity_scope and not any(fact.spatial_refs for fact in response.evidence_bundle.facts):
        # A broad context request may be satisfied without geometry.  A
        # spatial_lookup/gap request cannot be promoted to sufficient merely
        # because it returned aggregate prose.
        if request.request_type == "spatial_lookup" or request.query_purpose == "gap_resolution":
            return SufficiencyDecision(
                status=SufficiencyStatus.INSUFFICIENT_GEOMETRY,
                next_request=request.model_copy(update={"query_purpose": "gap_resolution"}),
                reason="retrieved evidence has no spatial references",
            )

    return SufficiencyDecision(status=SufficiencyStatus.SUFFICIENT, reason="all requested facts are covered")


__all__ = ["SufficiencyDecision", "SufficiencyStatus", "evaluate_sufficiency"]
