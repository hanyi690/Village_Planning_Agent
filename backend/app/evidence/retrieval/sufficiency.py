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


def _cjk_terms(value: str) -> list[str]:
    terms: list[str] = []
    run: list[str] = []
    for char in str(value or ""):
        if "\u4e00" <= char <= "\u9fff":
            run.append(char)
            continue
        if len(run) >= 2:
            terms.extend("".join(run[index : index + 2]) for index in range(len(run) - 1))
        run = []
    if len(run) >= 2:
        terms.extend("".join(run[index : index + 2]) for index in range(len(run) - 1))
    return list(dict.fromkeys(terms))


def _fact_covers_required(required: str, fact: object) -> bool:
    """Match identity questions against structured bundle facts.

    Chinese questions such as ``祠堂的BSM`` have no whitespace token boundary,
    while the answer fact is intentionally human-readable (``祠堂的 bundle
    feature BSM 为 ...``).  Use the typed field for the identity part and the
    Chinese mention for the semantic part; do not loosen ordinary fact
    matching globally.
    """
    statement = str(getattr(fact, "statement", "") or "").casefold()
    required_text = "".join(str(required or "").casefold().split())
    if not required_text or required_text in "".join(statement.split()):
        return True
    if str(getattr(fact, "fact_type", "") or "") != "bundle_feature_identity":
        return False
    fields = dict(getattr(fact, "fields", {}) or {})
    asks_for_bsm = "bsm" in required_text or "编码" in required_text
    if not asks_for_bsm or not fields.get("bundle_feature_bsm"):
        return False
    semantic_terms = _cjk_terms(required_text)
    return bool(semantic_terms) and all(term in statement for term in semantic_terms)


def _packet_covers_required(required: str, response: ExplorationResult) -> bool:
    """Use a verified spatial candidate for identity questions.

    A graph candidate is intentionally not rendered as prose containing the
    original mention (for example ``祠堂``); its identity stays structured in
    ``FeatureEvidenceRef``.  When the request itself names the semantic object
    and asks for its BSM/encoding, a bounded candidate ref is therefore
    sufficient evidence without forcing an external text search.
    """
    required_text = "".join(str(required or "").casefold().split())
    if not required_text or not any(token in required_text for token in ("bsm", "编码")):
        return False
    packet = getattr(response, "evidence_packet", None)
    candidates = list(getattr(packet, "candidate_refs", None) or [])
    if not candidates:
        return False
    request_text = "".join(
        str(getattr(packet, "request", "") or "").casefold().split()
    )
    semantic_terms = _cjk_terms(required_text)
    return bool(semantic_terms) and all(term in request_text for term in semantic_terms)


def evaluate_sufficiency(
    request: ExplorationRequest,
    response: ExplorationResult,
) -> SufficiencyDecision:
    """Classify evidence without treating ``facts != empty`` as success."""
    facts = _fact_text(response)
    typed_facts = list(response.evidence_bundle.facts)
    required = tuple(dict.fromkeys([
        *request.required_facts,
        *request.questions,
        *(item.statement for item in request.requirements if item.required),
    ]))
    missing = tuple(
        item
        for item in required
        if not _covered(item, facts)
        and not any(_fact_covers_required(item, fact) for fact in typed_facts)
        and not _packet_covers_required(item, response)
    )
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
