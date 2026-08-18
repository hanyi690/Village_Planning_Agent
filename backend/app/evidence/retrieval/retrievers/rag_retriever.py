"""Adapter exposing the legacy vector RAG as an Explore retriever."""

from __future__ import annotations

from typing import Any

from app.contracts.evidence.evidence_contracts import EvidenceFact, EvidenceSource

RETRIEVER_VERSION = "rag-adapter-v1"
_RAG_LOGS: dict[tuple[str, str], Any] = {}


def consume_rag_log(session_id: str, dimension_key: str) -> Any:
    return _RAG_LOGS.pop((str(session_id), str(dimension_key)), None)


async def retrieve_from_rag(
    session_id: str,
    dimension_key: str,
    stage: str = "",
    *,
    query: str = "",
    required_facts: list[str] | None = None,
    entity_scope: list[str] | None = None,
) -> tuple[list[EvidenceFact], list[EvidenceSource]]:
    """Call only the legacy implementation and return typed evidence rows."""
    from app.config import get_dimension_config
    from app.infrastructure.llm.dimension_runtime import _legacy_run_rag
    from app.infrastructure.runtime.planning_runtime_service import PlanningRuntimeService

    cfg = get_dimension_config(dimension_key)
    if cfg is None:
        return [], []
    state = await PlanningRuntimeService.aget_state_values(session_id) or {}
    state = dict(state)
    state.setdefault("session_id", session_id)
    context, log = await _legacy_run_rag(dimension_key, cfg, state)
    _RAG_LOGS[(str(session_id), str(dimension_key))] = log
    if not context:
        return [], []
    reference = f"rag:{session_id}:{dimension_key}"
    return [EvidenceFact(
        statement=context,
        confidence=0.7,
        source_refs=[reference],
        fact_type="rag_context",
        status="verified",
    )], [EvidenceSource(
        source_type="rag",
        reference=reference,
        confidence=0.7,
    )]


__all__ = ["RETRIEVER_VERSION", "consume_rag_log", "retrieve_from_rag"]
