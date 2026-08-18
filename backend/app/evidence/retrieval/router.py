"""Deterministic routing for Explore evidence requests.

The router is deliberately small and side-effect free.  It decides which
retrievers can answer a request; it never calls an external provider and it
does not manufacture facts.  Keeping this decision separate from the
retrievers makes gate retries bounded and auditable.
"""
from __future__ import annotations

from enum import StrEnum

from app.contracts.evidence.evidence_contracts import ExplorationRequest


class RetrieverKind(StrEnum):
    RAG = "rag"
    REPORT = "report"
    KG = "kg"
    BUNDLE = "bundle"
    ARTIFACT = "artifact"
    HISTORY = "history"
    INTEGRITY = "integrity"


def route_request(request: ExplorationRequest) -> list[RetrieverKind]:
    """Return the minimal deterministic source set for ``request``.

    A request can explicitly name a source in ``context_refs`` using
    ``source:<kind>``.  Otherwise the request type, purpose, gaps and scope
    select the sources.  The order is stable so the resulting evidence digest
    and cache key are stable too.
    """
    text = " ".join(
        [request.request_type, request.query_purpose, request.query]
        + list(request.questions)
        + list(request.required_facts)
        + list(request.evidence_gaps_to_resolve)
    ).lower()
    explicit = {
        ref.split(":", 1)[1].strip().lower()
        for ref in request.context_refs
        if isinstance(ref, str) and ref.startswith("source:") and ":" in ref
    }
    selected: set[RetrieverKind] = set()
    aliases = {kind.value: kind for kind in RetrieverKind}
    for value in explicit:
        if value in aliases:
            selected.add(aliases[value])

    request_type = request.request_type.lower()
    purpose = request.query_purpose.lower()
    scope = {item.lower() for item in request.entity_scope}

    if request_type in {"fact_check", "evidence_gap", "spatial_lookup"}:
        selected.update({RetrieverKind.REPORT, RetrieverKind.KG})
    if purpose in {"gap_resolution", "fact_check"} or request.required_facts:
        selected.add(RetrieverKind.ARTIFACT)
    if purpose in {"gap_resolution", "fact_check"} or request.context_refs:
        selected.add(RetrieverKind.HISTORY)
    if any(token in text for token in ("完整", "integrity", "crs", "覆盖", "字段", "版本", "空值")):
        selected.add(RetrieverKind.INTEGRITY)
    if scope or request_type == "spatial_lookup":
        selected.add(RetrieverKind.BUNDLE)

    # A gate gap about a concrete source must inspect that source even when
    # the request was emitted with a generic request_type.
    if any(token in text for token in ("artifact", "产物", "快照", "planned_state", "grounding_result")):
        selected.add(RetrieverKind.ARTIFACT)
    if any(token in text for token in ("history", "历史", "checkpoint", "revision", "修订")):
        selected.add(RetrieverKind.HISTORY)

    return [kind for kind in RetrieverKind if kind in selected]


__all__ = ["RetrieverKind", "route_request"]
