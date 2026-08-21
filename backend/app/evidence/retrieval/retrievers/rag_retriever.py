"""Adapter exposing the optional professional vector RAG corpus as evidence."""

from __future__ import annotations

import hashlib
from typing import Any

from app.contracts.evidence.evidence_contracts import EvidenceFact, EvidenceSource

RETRIEVER_VERSION = "rag-adapter-v2"
_RAG_LOGS: dict[tuple[str, str], Any] = {}
_MAX_VECTOR_CHUNKS = 8
_MAX_CHUNK_CHARS = 600


def consume_rag_log(session_id: str, dimension_key: str) -> Any:
    return _RAG_LOGS.pop((str(session_id), str(dimension_key)), None)


def peek_rag_log(session_id: str, dimension_key: str) -> Any:
    """Read availability metadata without consuming the worker hand-off."""
    return _RAG_LOGS.get((str(session_id), str(dimension_key)))


def clear_rag_logs(session_id: str) -> None:
    """Release all per-session RAG availability logs."""
    session_key = str(session_id or "")
    if not session_key:
        return
    for key in [key for key in _RAG_LOGS if key[0] == session_key]:
        _RAG_LOGS.pop(key, None)


def _chunk_fact(chunk: Any, dimension_key: str) -> tuple[EvidenceFact, EvidenceSource] | None:
    statement = str(getattr(chunk, "content_preview", "") or "").strip()
    if not statement:
        return None
    source = str(getattr(chunk, "source", "") or "unknown").strip()
    chunk_id = str(getattr(chunk, "chunk_id", "") or "").strip()
    if not chunk_id:
        chunk_id = hashlib.sha256(statement.encode("utf-8")).hexdigest()[:16]
    source_ref = f"rag-vector:{source}:chunk:{chunk_id}"
    # The vector-store score is a distance-like value: smaller is
    # better. Clamp it so malformed provider results cannot dominate local
    # authoritative evidence.
    try:
        distance = float(getattr(chunk, "score", 0.0) or 0.0)
    except (TypeError, ValueError):
        distance = 0.0
    confidence = max(0.35, min(0.9, 1.0 - distance))
    span = statement[:_MAX_CHUNK_CHARS]
    fact = EvidenceFact(
        statement=span,
        confidence=round(confidence, 3),
        source_refs=[source_ref],
        fact_type="professional_text",
        fields={
            "evidence_role": "planning_background",
            "source_kind": "external_vector_corpus",
            "source_title": str(getattr(chunk, "title", "") or ""),
            "doc_type": str(getattr(chunk, "doc_type", "") or ""),
            "dimension_key": dimension_key,
            "retrieval_mode": "vector",
        },
        evidence_span=span,
        source_locator=source_ref,
        support_relation="professional_reference",
        status="needs_review",
        evidence_role="planning_background",
        source_kind="external_vector_corpus",
        spatial_granularity="none",
        planning_use="context",
    )
    return fact, EvidenceSource(
        source_type="rag",
        reference=source_ref,
        confidence=fact.confidence,
    )


async def retrieve_from_rag(
    session_id: str,
    dimension_key: str,
    stage: str = "",
    *,
    query: str = "",
    required_facts: list[str] | None = None,
    entity_scope: list[str] | None = None,
) -> tuple[list[EvidenceFact], list[EvidenceSource]]:
    """Retrieve only professional vector-corpus chunks.

    ``query``, ``required_facts`` and ``entity_scope`` are forwarded through
    the unified adapter. The vector runtime currently owns vector query
    generation, so the adapter preserves its log while projecting each
    returned chunk to an auditable EvidenceFact. No session-owned evidence is
    synthesized here.
    """
    from app.config import get_dimension_config
    from app.infrastructure.llm.dimension_runtime import retrieve_vector_context
    from app.infrastructure.runtime.planning_runtime_service import PlanningRuntimeService

    cfg = get_dimension_config(dimension_key)
    if cfg is None:
        return [], []
    state = await PlanningRuntimeService.aget_state_values(session_id) or {}
    state = dict(state)
    state.setdefault("session_id", session_id)
    _context, log = await retrieve_vector_context(dimension_key, cfg, state)
    _RAG_LOGS[(str(session_id), str(dimension_key))] = log

    facts: list[EvidenceFact] = []
    sources: list[EvidenceSource] = []
    seen: set[str] = set()
    for chunk in list(getattr(log, "retrieved_chunks", []) or [])[:_MAX_VECTOR_CHUNKS]:
        projected = _chunk_fact(chunk, dimension_key)
        if projected is None:
            continue
        fact, source = projected
        if source.reference in seen:
            continue
        seen.add(source.reference)
        facts.append(fact)
        sources.append(source)

    return facts, sources


__all__ = [
    "RETRIEVER_VERSION",
    "clear_rag_logs",
    "consume_rag_log",
    "peek_rag_log",
    "retrieve_from_rag",
]
