"""Build stable, bounded sub-queries from Explore gaps."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

from app.contracts.evidence.evidence_contracts import ExplorationRequest
from app.evidence.retrieval.router import RetrieverKind, route_request


@dataclass(frozen=True)
class EvidenceQuery:
    retriever: RetrieverKind
    query: str
    entity_scope: tuple[str, ...] = ()
    required_facts: tuple[str, ...] = ()
    source_refs: tuple[str, ...] = ()


@dataclass(frozen=True)
class EvidenceQueryPlan:
    request_fingerprint: str
    queries: tuple[EvidenceQuery, ...] = ()
    max_rounds: int = 2

    @property
    def retrievers(self) -> tuple[RetrieverKind, ...]:
        return tuple(dict.fromkeys(item.retriever for item in self.queries))


def request_fingerprint(request: ExplorationRequest) -> str:
    payload = request.model_dump(mode="json")
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _terms(request: ExplorationRequest) -> list[str]:
    values = [request.query.strip(), *request.questions, *request.required_facts, *request.evidence_gaps_to_resolve]
    result: list[str] = []
    for value in values:
        normalized = " ".join(str(value).split())
        if normalized and normalized not in result:
            result.append(normalized)
    return result[:8]


def build_query_plan(
    request: ExplorationRequest,
    *,
    project_wide: bool = False,
) -> EvidenceQueryPlan:
    """Create one bounded query per routed retriever.

    Every query carries the full scope and required facts.  This prevents the
    old behaviour where each retriever received only ``dimension_key`` and
    could not distinguish a gate gap from broad context injection.
    """
    terms = _terms(request)
    base_query = "；".join(terms) or request.dimension_key or request.request_type
    required = tuple(dict.fromkeys([*request.required_facts, *request.questions]))
    scope = tuple(dict.fromkeys(request.entity_scope))
    source_refs = tuple(dict.fromkeys(request.context_refs))
    queries = tuple(
        EvidenceQuery(
            retriever=kind,
            query=base_query,
            entity_scope=scope,
            required_facts=required,
            source_refs=source_refs,
        )
        for kind in route_request(request, project_wide=project_wide)
    )
    return EvidenceQueryPlan(
        request_fingerprint=request_fingerprint(request),
        queries=queries,
        max_rounds=2,
    )


__all__ = ["EvidenceQuery", "EvidenceQueryPlan", "build_query_plan", "request_fingerprint"]
