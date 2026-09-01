"""Shared Evidence Runtime adapter for L1/L2/L3 dimension work.

This module owns the runtime-side evidence retrieval and bounded I/O hand-off
that dimension workers reuse: RAG retrieval,
dependency report loading, SSE publishing, ReportStore save, StepReport
save, and structured summary generation without importing the whole
dimension analysis pipeline.

Business modules only declare the dimension requirement and consume the
projection returned by ``modules.evidence``. All helpers here are wrappers
over I/O dependencies (RagService,
PlanningRuntimeService, sse_manager, ReportStore, step_report service,
summary generator) and are non-fatal where the original L1 code was.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional

from app.config import get_dimension_layer
from app.contracts.events import SSEEventType
from app.infrastructure.logging import get_logger

logger = get_logger(__name__)

_PROVIDER_QUOTA_MARKERS = (
    "gousagelimiterror",
    "weekly usage limit",
    "quota exceeded",
    "insufficient balance",
)


def is_provider_quota_exhausted(exc: BaseException) -> bool:
    """Return true when retrying cannot change the provider quota state."""
    message = str(exc or "").lower()
    return any(marker in message for marker in _PROVIDER_QUOTA_MARKERS)

# Provider failures are session-scoped circuit-breaker events. A LangGraph
# layer fans out several dimensions concurrently; consecutive transport
# failures open the circuit so a sustained outage does not spend the whole
# layer budget, while one transient 5xx can recover on the next call.
_PROVIDER_FAILURE_LOCK = threading.Lock()
_PROVIDER_FAILURE_COUNTS: dict[str, int] = {}
_PROVIDER_FAILURE_SESSIONS: set[str] = set()


def reset_provider_failure(session_id: str) -> None:
    if session_id:
        with _PROVIDER_FAILURE_LOCK:
            _PROVIDER_FAILURE_COUNTS.pop(session_id, None)
            _PROVIDER_FAILURE_SESSIONS.discard(session_id)


def provider_failure_open(session_id: str) -> bool:
    if not session_id:
        return False
    with _PROVIDER_FAILURE_LOCK:
        return session_id in _PROVIDER_FAILURE_SESSIONS


def trip_provider_failure(session_id: str) -> None:
    if session_id:
        with _PROVIDER_FAILURE_LOCK:
            count = _PROVIDER_FAILURE_COUNTS.get(session_id, 0) + 1
            _PROVIDER_FAILURE_COUNTS[session_id] = count
            from app.core.llm_config import get_llm_settings

            threshold = max(
                1,
                int(get_llm_settings().provider_circuit_failure_threshold),
            )
            if count >= threshold:
                _PROVIDER_FAILURE_SESSIONS.add(session_id)


def is_provider_failure(exc: BaseException) -> bool:
    """Return whether an exception is transport/provider infrastructure failure.

    Instructor schema validation and max-token truncation are contract defects,
    not evidence that the upstream service is unavailable. Only transport,
    HTTP API, and asyncio timeout errors should advance the circuit breaker.
    """
    if isinstance(exc, asyncio.TimeoutError):
        return True
    from app.infrastructure.structured_runtime.parser import provider_failure_code

    if provider_failure_code(exc) is not None:
        return True
    try:
        import httpx
        from openai import APIError

        return isinstance(exc, (APIError, httpx.HTTPError))
    except ImportError:
        return False


def dimension_failure_attempt(state: dict[str, Any], dimension_key: str) -> dict[str, int]:
    """Return a monotonic per-dimension failure count for checkpoint audits."""
    counts = dict(state.get("dimension_retry_counts") or {})
    key = str(dimension_key or "unknown")
    try:
        counts[key] = int(counts.get(key, 0)) + 1
    except (TypeError, ValueError):
        counts[key] = 1
    return counts


def strip_model_reasoning(content: str) -> str:
    """Remove provider reasoning envelopes before persistence or reuse as evidence."""
    cleaned = re.sub(
        r"<(?:think|analysis)>.*?</(?:think|analysis)>",
        "",
        content or "",
        flags=re.IGNORECASE | re.DOTALL,
    )
    return cleaned.strip()


# ============================================
# RAG Retrieval Logging
# ============================================


@dataclass
class RetrievedChunk:
    """单个检索到的切片"""

    chunk_id: str
    content_preview: str
    source: str
    score: float
    doc_type: str = ""
    title: str = ""
    category: str = ""
    subcategory: str = ""


@dataclass
class RAGRetrievalLog:
    """RAG检索日志"""

    dimension_key: str
    query: str
    query_generation_method: str  # "llm" or "template"
    retrieved_chunks: List[RetrievedChunk]
    total_results: int
    retrieval_latency_ms: float
    context_length: int
    context_truncated: bool
    rag_enabled: bool
    skip_reason: str  # 如果RAG被跳过，记录原因


async def _current_planning_context(state: Dict[str, Any]) -> Any:
    """Return the workflow-owned context required by every evidence request."""

    session_id = str((state or {}).get("session_id", "") or "").strip()
    if not session_id:
        raise RuntimeError("PLANNING_CONTEXT_UNAVAILABLE: missing session_id")
    from app.infrastructure.context_runtime.manager import get_cached_context

    context = get_cached_context(session_id)
    if context is None:
        from app.workflow.stages.support import _require_context

        await _require_context(state)
        context = get_cached_context(session_id)
    if context is None:
        raise RuntimeError("PLANNING_CONTEXT_UNAVAILABLE: context is not hydrated")
    return context


def _project_cognition_scope(
    context: Any,
    state: Dict[str, Any],
    entity_scope: list[str],
) -> dict[str, Any]:
    """Build the small request scope passed to ProjectCognition."""

    config = (state or {}).get("config") or {}
    supplied = (state or {}).get("project_scope") or config.get("project_scope") or {}
    if not isinstance(supplied, dict):
        supplied = {}
    spatial = supplied.get("spatial_scope")
    if not isinstance(spatial, dict):
        spatial = {
            key: supplied[key]
            for key in ("spatial_ref", "bbox", "geometry_ref", "crs", "village_name")
            if key in supplied
        }
    else:
        spatial = dict(spatial)
    spatial["entity_scope"] = list(dict.fromkeys(
        str(value).strip() for value in entity_scope if str(value).strip()
    ))
    context_village = str(getattr(context, "village_name", "") or "").strip()
    if context_village:
        spatial["village_name"] = context_village
    scope = {"spatial_scope": spatial}
    time_scope = supplied.get("time_scope")
    if isinstance(time_scope, dict):
        scope["time_scope"] = dict(time_scope)
    return scope


def _analysis_evidence_context(
    result: Any,
    *,
    budget: int = 48,
    excluded_source_families: set[str] | None = None,
    excluded_fact_refs: Iterable[str] | None = None,
) -> str:
    """Render only the analysis-safe evidence projection.

    Query plans, query traces, raw rows and report bodies remain in the
    retrieval/audit plane.  ``render_analysis_evidence`` projects the existing
    EvidenceBundle/EvidencePacket contracts without creating a second evidence
    contract.
    """

    from app.infrastructure.context_runtime.projection_builder import (
        render_analysis_evidence_for_prompt,
    )

    projection = render_analysis_evidence_for_prompt(
        result,
        budget=min(budget, 16),
        include_packet_spatial=False,
    )
    excluded = {str(item).strip() for item in (excluded_source_families or set())}
    if excluded:
        projection["facts"] = [
            fact
            for fact in projection.get("facts", [])
            if not excluded.intersection(fact.get("source_families", []))
        ]
        projection["sources"] = [
            source
            for source in projection.get("sources", [])
            if source.get("source_family") not in excluded
        ]
    excluded_refs = {
        str(item).strip()
        for item in (excluded_fact_refs or ())
        if str(item).strip()
    }
    if excluded_refs:
        projection["facts"] = [
            fact
            for fact in projection.get("facts", [])
            if not excluded_refs.intersection({
                str(fact.get("fact_id") or "").strip(),
                *(str(ref).strip() for ref in fact.get("source_refs", []) or []),
                *(str(ref).strip() for ref in fact.get("evidence_refs", []) or []),
            })
        ]
    sections = ["## EXPLORE 证据"]
    facts = projection.get("facts", [])
    if facts:
        from app.infrastructure.context_runtime import build_bounded_table

        _, fact_table = build_bounded_table(
            (
                "fact_id",
                "statement",
                "subject_ref",
                "predicate",
                "value",
                "source_refs",
                "evidence_refs",
            ),
            facts,
            max_rows=min(budget, 16),
            max_chars=6200,
        )
        sections.extend(["### 事实", fact_table])
    coverage = projection.get("coverage", {})
    if coverage:
        from app.infrastructure.context_runtime import build_bounded_table

        _, coverage_table = build_bounded_table(
            ("field", "value"),
            [
                {"field": key, "value": value}
                for key, value in coverage.items()
            ],
            max_rows=24,
            max_chars=5000,
        )
        sections.extend(["### 覆盖状态", coverage_table])
    gaps = projection.get("gap", [])
    if gaps:
        from app.infrastructure.context_runtime import build_bounded_table

        _, gap_table = build_bounded_table(
            ("gap_id", "status", "reason"),
            gaps,
            max_rows=min(budget, 16),
            max_chars=5000,
        )
        sections.extend(["### 证据缺口", gap_table])
    return "\n".join(sections)


async def retrieve_vector_context(dimension_key: str, cfg: Any, state: Dict[str, Any]) -> tuple[str, Any | None]:
    """Run the internal vector provider used by the unified evidence router.

    The returned context string is intentionally empty.  Vector chunks remain
    available to the router as typed evidence; report-style prompt prose is
    not an analysis-layer output.
    """
    from app.infrastructure.runtime.planning_runtime_service import PlanningRuntimeService

    await _current_planning_context(state)
    session_id = state.get("session_id", "")
    config = state.get("config", {})
    dim_layer = getattr(cfg, "layer", get_dimension_layer(dimension_key) or 3)
    prefer_doc_types = getattr(cfg, "prefer_doc_types", None) or None

    if provider_failure_open(session_id):
        return (
            "",
            RAGRetrievalLog(
                dimension_key=dimension_key,
                query="",
                query_generation_method="circuit_open",
                retrieved_chunks=[],
                total_results=0,
                retrieval_latency_ms=0,
                context_length=0,
                context_truncated=False,
                rag_enabled=False,
                skip_reason="LLM provider circuit is open",
            ),
        )

    _latest = await PlanningRuntimeService.aget_state_values(session_id)
    live_config = _latest.get("config", {}) if _latest else config

    from app.core import settings

    default_rag_enabled = bool(getattr(settings, "RAG_ENABLED", False))
    rag_layer_config = live_config.get("rag_layer_config", {})
    global_rag_enabled = live_config.get("rag_enabled", default_rag_enabled)
    layer_rag_enabled = rag_layer_config.get(dim_layer, global_rag_enabled)
    dim_rag_query = getattr(cfg, "rag_query", "")
    rag_enabled = layer_rag_enabled and global_rag_enabled

    if not rag_enabled or not dim_rag_query:
        skip_reason = (
            "disabled_by_config"
            if not rag_enabled
            else "dimension_rag_query_missing"
        )
        return (
            "",
            RAGRetrievalLog(
                dimension_key=dimension_key,
                query="",
                query_generation_method="disabled",
                retrieved_chunks=[],
                total_results=0,
                retrieval_latency_ms=0,
                context_length=0,
                context_truncated=False,
                rag_enabled=False,
                skip_reason=skip_reason,
            ),
        )

    from app.infrastructure.events import event_hub as sse_manager
    from app.infrastructure.rag.service import RagService

    rag_service = RagService.get_instance()
    if getattr(rag_service, "_vector_store", None) is None:
        return (
            "",
            RAGRetrievalLog(
                dimension_key=dimension_key,
                query="",
                query_generation_method="skipped_unavailable",
                retrieved_chunks=[],
                total_results=0,
                retrieval_latency_ms=0,
                context_length=0,
                context_truncated=False,
                rag_enabled=False,
                skip_reason="vector store unavailable; skipped query generation",
            ),
        )

    knowledge_cache = config.get("knowledge_cache", {})
    if state.get("is_revision") and dimension_key in knowledge_cache:
        cached = knowledge_cache[dimension_key]
        logger.info(f"[dimension_runtime] {dimension_key}: RAG cache hit")
        rlog = RAGRetrievalLog(
            dimension_key=dimension_key, query=cached.get("query", ""),
            query_generation_method="cached", retrieved_chunks=[],
            total_results=cached.get("total_results", 0), retrieval_latency_ms=0,
            context_length=0, context_truncated=False,
            rag_enabled=True, skip_reason="",
        )
        await sse_manager.publish(session_id, {
            "type": SSEEventType.RAG_RESULT, "dimension_key": dimension_key, "layer": dim_layer,
            "query": cached.get("query", ""),
            "query_generation_method": "cached", "retrieval_latency_ms": 0,
            "total_results": cached.get("total_results", 0),
            "documents": cached.get("documents", []),
        })
        return ("", rlog)

    start_time = time.time()
    try:
        queries = await rag_service.generate_queries(cfg, state)
        query_method = "llm_multi"

        # Notify frontend that RAG queries have been generated
        await sse_manager.publish(session_id, {
            "type": SSEEventType.RAG_QUERY,
            "dimension_key": dimension_key,
            "layer": dim_layer,
            "query": queries[0] if queries else "",
        })

        # Cross-dimension query result cache
        _query_cache = config.setdefault("_query_result_cache", {})
        uncached_queries = []
        cached_results = []
        for query in queries:
            qhash = hashlib.md5(query.encode()).hexdigest()[:16]
            if qhash in _query_cache:
                cached_results.extend(_query_cache[qhash])
            else:
                uncached_queries.append((query, qhash))

        search_tasks = [rag_service.search(q, top_k=5, prefer_doc_types=prefer_doc_types) for q, _ in uncached_queries]

        fresh_results = await asyncio.gather(*search_tasks) if search_tasks else []

        # Merge cached + fresh results
        result_idx = 0
        all_results_nested = []
        for query in queries:
            qhash = hashlib.md5(query.encode()).hexdigest()[:16]
            if qhash in _query_cache:
                all_results_nested.append([{**r, "matched_query": query} for r in _query_cache[qhash]])
            else:
                fresh = fresh_results[result_idx]
                result_idx += 1
                all_results_nested.append(fresh)
                _query_cache[qhash] = fresh
        all_results = [
            {**r, "matched_query": queries[query_idx]}
            for query_idx, query_results in enumerate(all_results_nested)
            for r in query_results
        ]
        seen_content = set()
        unique_results = []
        for r in sorted(all_results, key=lambda x: x.get("score", 999)):
            content_key = r.get("content", "")[:100]
            if content_key not in seen_content:
                seen_content.add(content_key)
                unique_results.append(r)
        results = unique_results[:5]

        # 过滤无效结果：只有标题标记且无实质内容的切片
        valid_results = []
        for r in results:
            content = r.get("content", "").strip()
            if len(content) < 50 and content.startswith("#"):
                logger.debug(f"[dimension_runtime] 过滤无效标题切片: {content[:50]}")
                continue
            valid_results.append(r)
        results = valid_results

        latency_ms = (time.time() - start_time) * 1000

        retrieved_chunks = []
        for r in results:
            chunk = RetrievedChunk(
                chunk_id=str(hash(r.get("content", "")[:100])),
                content_preview=r.get("content", ""),
                source=r.get("metadata", {}).get("source", "unknown"),
                score=r.get("score", 0.0),
                doc_type=r.get("metadata", {}).get("doc_type", ""),
                title=r.get("metadata", {}).get("title", ""),
                category=r.get("metadata", {}).get("category", ""),
                subcategory=r.get("metadata", {}).get("subcategory", ""),
            )
            retrieved_chunks.append(chunk)

        rlog = RAGRetrievalLog(
            dimension_key=dimension_key, query=queries[0] if queries else "",
            query_generation_method=query_method, retrieved_chunks=retrieved_chunks,
            total_results=len(results), retrieval_latency_ms=latency_ms,
            context_length=0, context_truncated=False,
            rag_enabled=True, skip_reason="",
        )
        await sse_manager.publish(session_id, {
            "type": SSEEventType.RAG_RESULT, "dimension_key": dimension_key, "layer": dim_layer,
            "query": queries[0] if queries else "",
            "query_generation_method": query_method,
            "retrieval_latency_ms": latency_ms,
            "total_results": len(results),
            "documents": [{
                "title": r.get("metadata", {}).get("title", "") or r.get("metadata", {}).get("source", "未知"),
                "snippet": (r.get("content", "") or "")[:300],
                "source": r.get("metadata", {}).get("source", "未知"),
                "matched_query": r.get("matched_query", ""),
                "ancestors": r.get("metadata", {}).get("ancestors", []),
                "section_title": r.get("metadata", {}).get("section_title", ""),
                "parent_section_title": r.get("metadata", {}).get("parent_section_title", ""),
                "score": r.get("score", 0),
            } for r in results],
        })
        logger.info(
            f"[dimension_runtime] {dimension_key}: RAG retrieved {len(results)} chunks, {latency_ms:.1f}ms"
        )
        return ("", rlog)
    except Exception as e:
        message = str(e).lower()
        if any(marker in message for marker in (
            "invalid_api_key", "arrearage", "access denied", "401", "402",
        )):
            trip_provider_failure(session_id)
        logger.error(f"[dimension_runtime] {dimension_key}: RAG failed: {e}")
        rlog = RAGRetrievalLog(
            dimension_key=dimension_key, query="", query_generation_method="failed",
            retrieved_chunks=[], total_results=0, retrieval_latency_ms=0,
            context_length=0, context_truncated=False, rag_enabled=False, skip_reason=str(e),
        )
        return ("", rlog)


def _compact_planning_query_text(value: Any, limit: int) -> str:
    """Keep planning retrieval context bounded without classifying prose."""
    if isinstance(value, (list, tuple, set)):
        value = " ".join(str(item or "") for item in value)
    if isinstance(value, dict):
        value = " ".join(
            f"{key} {item}" for key, item in value.items()
        )
    return " ".join(str(value or "").split()).strip()[:limit]


def _planning_evidence_query(
    dimension_key: str,
    cfg: Any,
    state: Dict[str, Any],
    *,
    context: Any = None,
) -> str:
    """Build the bounded semantic query used by planning workers.

    The query is only a retrieval input.  It does not resolve a name or
    manufacture a spatial identity.  Typed L1 location facts add recall for
    names that are absent from the KG/bundle labels; the EvidenceGraph still
    decides which Bundle feature is authoritative.
    """
    config = state.get("config") or {}
    session_id = str(state.get("session_id", "") or "").strip()
    if context is None and session_id:
        try:
            from app.infrastructure.context_runtime.manager import (
                get_cached_context,
            )

            context = get_cached_context(session_id)
        except Exception:
            context = None

    input_texts = {}
    if context is not None:
        try:
            input_texts = context.input_texts()
        except Exception:
            input_texts = {}

    values: list[str] = []
    seen: set[str] = set()

    def add(value: Any, limit: int) -> None:
        text = _compact_planning_query_text(value, limit)
        if not text:
            return
        key = text.casefold()
        if key not in seen:
            seen.add(key)
            values.append(text)

    add(
        (
            getattr(context, "village_name", "")
            if context is not None
            else ""
        )
        or config.get("village_name", ""),
        120,
    )
    add(getattr(cfg, "name", "") or dimension_key, 160)
    add(dimension_key, 120)
    add(input_texts.get("task_description") or config.get("task_description", ""), 520)
    add(input_texts.get("constraints") or config.get("constraints", ""), 420)

    # Location mentions are compact semantic anchors, not an LLM-generated
    # identity.  Keep them bounded so a large L1 snapshot cannot consume the
    # planning prompt budget.
    for fact in list(getattr(context, "location_facts", []) or [])[:24]:
        add(
            " ".join(
                str(value or "")
                for value in (
                    getattr(fact, "mention", ""),
                    getattr(fact, "normalized_name", ""),
                    getattr(fact, "role", ""),
                    getattr(fact, "spatial_hint", ""),
                    " ".join(getattr(fact, "aliases", []) or []),
                )
            ),
            220,
        )

    for record in list(getattr(context, "l1_fact_records", []) or [])[:24]:
        semantic_type = str(getattr(record, "semantic_type", "") or "").strip()
        attributes = getattr(record, "attributes", None) or {}
        spatial_values = [
            attributes.get(key, "")
            for key in (
                "location",
                "spatial_hint",
                "normalized_name",
                "village",
                "settlement",
                "natural_village",
            )
        ]
        if not any(str(value or "").strip() for value in spatial_values):
            if semantic_type.casefold() not in {
                "facility", "hazard", "landmark", "road", "water", "parcel",
                "place", "settlement", "village", "zone", "infrastructure",
            }:
                continue
        add(
            " ".join(
                str(value or "")
                for value in (
                    getattr(record, "subject_scope", ""),
                    semantic_type,
                    *spatial_values,
                    getattr(record, "statement", ""),
                )
            ),
            260,
        )

    return _compact_planning_query_text(" ".join(values), 1800)


async def run_rag(
    dimension_key: str,
    cfg: Any,
    state: Dict[str, Any],
    *,
    trace_sink: dict[str, Any] | None = None,
    excluded_fact_refs: Iterable[str] | None = None,
) -> tuple[str, Any | None]:
    """Retrieve one unified evidence packet for a planning dimension.

    Dimension workers call this one entry point; they must not append a second
    retrieval section themselves.  The returned string is an analysis-only
    projection, while the packet and query trace remain in the evidence plane.
    """
    from app.contracts.evidence.evidence_contracts import ExplorationRequest
    from app.infrastructure.evidence_runtime.facade import retrieve_evidence

    session_id = str(state.get("session_id", "") or "")
    config = state.get("config") or {}
    context = await _current_planning_context(state)
    from app.modules.l1.dimension_contracts import get_dimension_entity_scope

    entity_scope = get_dimension_entity_scope(dimension_key, cfg)
    if not entity_scope:
        raise ValueError(f"No retrieval entity scope configured for {dimension_key!r}")
    project_cognition_scope = _project_cognition_scope(
        context,
        state,
        entity_scope,
    )
    from app.infrastructure.context_runtime.projection_builder import build_project_cognition

    project_cognition = build_project_cognition(context, project_cognition_scope)
    external_enabled = str(
        config.get(
            "evidence_external_for_llm",
            os.getenv("EVIDENCE_EXTERNAL_FOR_LLM", "false"),
        )
    ).strip().lower() in {"1", "true", "yes", "on"}
    external_kwargs: dict[str, Any] = {}
    owned_external_provider = False
    context_refs = []
    if external_enabled:
        # External evidence is deliberately an explicit planning opt-in.  In
        # the normal application path the lifecycle-owned provider is reused;
        # a typed unavailable adapter is used only for an explicit opt-in with
        # no configured provider, so the LLM sees a diagnostic rather than a
        # silent omission.  Neither path creates geometry or source identity.
        try:
            from app.infrastructure.search.provider_registry import (
                get_active_external_provider,
                get_configured_external_provider,
            )
            from app.infrastructure.evidence_runtime.context_hydration import build_external_evidence_policy

            external_port = get_active_external_provider()
            if external_port is None:
                external_port = get_configured_external_provider()
                owned_external_provider = True
            external_kwargs = {
                "external_port": external_port,
                "external_policy": build_external_evidence_policy(dimension_key),
            }
            context_refs.append("source:external")
        except Exception as exc:  # noqa: BLE001 - explicit opt-in remains typed
            logger.warning(
                "[dimension_runtime] external evidence setup failed for %s: %s",
                dimension_key,
                exc,
            )
            from app.infrastructure.evidence_runtime.external_search_policy import ExternalSearchPolicy
            from app.infrastructure.search import UnavailableExternalSearchAdapter

            external_kwargs = {
                "external_port": UnavailableExternalSearchAdapter(),
                "external_policy": ExternalSearchPolicy(
                    allowed_dimensions=[dimension_key],
                ),
            }
            context_refs.append("source:external")
    request = ExplorationRequest(
        run_id=f"{session_id}:{dimension_key}:adapter",
        request_type="spatial_lookup",
        query=_planning_evidence_query(
            dimension_key,
            cfg,
            state,
            context=context,
        ),
        stage=f"L{getattr(cfg, 'layer', 3)}",
        dimension_key=dimension_key,
        query_purpose="context_injection",
        entity_scope=entity_scope,
        context_refs=context_refs,
        project_cognition_digest=project_cognition.cognition_digest,
        project_scope=project_cognition.spatial_scope,
    )
    world_model_mode = str(
        getattr(context, "world_model_mode", "off") or "off"
    ).strip().lower()
    v2_mode = world_model_mode in {"prefer_v2", "v2_only"}
    shadow_mode = world_model_mode == "shadow"
    try:
        if (v2_mode or shadow_mode) and getattr(context, "data_resource_catalog", None) is not None:
            from app.contracts.evidence.requirement_contracts import EvidenceRequirement
            from app.modules.evidence.application import EvidenceApplication, EvidenceContext

            requirement = EvidenceRequirement(
                requirement_id=f"{session_id}:{dimension_key}:dimension",
                request_id=request.run_id,
                producer_stage=request.stage or "L1",
                statement=request.query,
                kind="spatial" if entity_scope else "claim",
                scope=tuple(entity_scope),
                spatial_granularity="feature" if entity_scope else "none",
                allowed_inference="exact",
                evidence_role="dimension_context",
            )
            v2_result = await EvidenceApplication().retrieve(
                requirement,
                EvidenceContext.from_runtime_context(
                    context,
                    session_id=session_id,
                    run_id=request.run_id,
                    stage=request.stage,
                    dimension_key=dimension_key,
                    purpose="context_injection",
                    request_type=request.request_type,
                    context_refs=tuple(request.context_refs),
                ),
                candidate_limit=32,
            )
            if shadow_mode:
                # Legacy remains the read authority in shadow mode.  Execute
                # the V2 query beside it and record only opaque candidate refs.
                legacy_result = await retrieve_evidence(
                    request,
                    session_id=session_id,
                    village_name=str(
                        getattr(context, "village_name", "")
                        or config.get("village_name", "")
                        or ""
                    ),
                    **external_kwargs,
                )
                result = legacy_result
                try:
                    from app.infrastructure.cognition_runtime.shadow_compare import record_shadow_stage

                    record_shadow_stage(
                        session_id=session_id,
                        stage=request.stage or "L1",
                        dimension_key=dimension_key,
                        v1_refs=getattr(getattr(legacy_result, "evidence_packet", None), "candidate_refs", ()) or (),
                        v2_refs=getattr(getattr(v2_result, "evidence_packet", None), "candidate_refs", ()) or (),
                        details="shadow evidence retrieval; legacy result returned",
                        v1_available=getattr(legacy_result, "evidence_packet", None) is not None,
                        v2_available=getattr(v2_result, "evidence_packet", None) is not None,
                    )
                except Exception as exc:  # shadow audit must not change authority
                    logger.debug("[dimension_runtime] shadow stage diff failed: %s", exc)
            else:
                result = v2_result
        else:
            result = await retrieve_evidence(
                request,
                session_id=session_id,
                village_name=str(
                    getattr(context, "village_name", "")
                    or config.get("village_name", "")
                    or ""
                ),
                **external_kwargs,
            )
    finally:
        if owned_external_provider:
            close = getattr(external_kwargs.get("external_port"), "close", None)
            if callable(close):
                try:
                    outcome = close()
                    if hasattr(outcome, "__await__"):
                        await outcome
                except Exception as exc:  # noqa: BLE001 - cleanup is best effort
                    logger.warning(
                        "[dimension_runtime] external provider cleanup failed: %s",
                        exc,
                    )
    bundle = getattr(result, "evidence_bundle", None)
    packet = getattr(result, "evidence_packet", None)
    spatial_cognition = getattr(result, "spatial_cognition", None)
    coverage = getattr(result, "coverage", None)
    if trace_sink is not None:
        sources = list(getattr(bundle, "sources", None) or [])
        evidence_ref_catalog: set[str] = set()
        try:
            from app.infrastructure.context_runtime.projection_builder import (
                render_analysis_evidence_for_prompt,
            )

            prompt_projection = render_analysis_evidence_for_prompt(
                result,
                budget=16,
                include_packet_spatial=False,
            )
            for fact in prompt_projection.get("facts", []):
                if not isinstance(fact, dict):
                    continue
                evidence_ref_catalog.update(
                    str(value).strip()
                    for key in ("fact_id", "source_refs", "evidence_refs")
                    for value in (
                        fact.get(key, [])
                        if isinstance(fact.get(key), (list, tuple, set))
                        else [fact.get(key)]
                    )
                    if str(value or "").strip()
                )
        except Exception as exc:  # noqa: BLE001 - catalog is an optional projection
            logger.debug(
                "[dimension_runtime] evidence ref catalog unavailable for %s: %s",
                dimension_key,
                exc,
            )
        trace_sink.update({
            "source_types": sorted({
                str(getattr(source, "source_type", "") or "").strip()
                for source in sources
                if str(getattr(source, "source_type", "") or "").strip()
            }),
            "fact_count": len(getattr(bundle, "facts", None) or []),
            "kg_confidence": float(
                getattr(spatial_cognition, "kg_confidence", 0.0) or 0.0
            ),
            "candidate_count": len(getattr(packet, "candidate_refs", None) or []),
            "relation_count": len(getattr(packet, "relation_evidence", None) or []),
            "coverage_status": str(
                getattr(coverage, "stop_reason", "") or ""
            ),
            "coverage_sufficient": bool(
                getattr(coverage, "sufficient", False)
            ),
            "unresolved_count": len(
                getattr(bundle, "unresolved", None) or []
            ),
            "project_cognition_digest": project_cognition.cognition_digest,
            "project_scope": project_cognition.spatial_scope,
            "evidence_ref_catalog": sorted(evidence_ref_catalog)[:128],
        })
    rag_log = None
    try:
        from app.infrastructure.evidence_runtime.retrievers.rag_retriever import consume_rag_log

        rag_log = consume_rag_log(session_id, dimension_key)
    except Exception:
        rag_log = None
    excluded_source_families = {"l1"} if int(getattr(cfg, "layer", 3) or 3) >= 2 else set()
    return _analysis_evidence_context(
        result,
        excluded_source_families=excluded_source_families,
        excluded_fact_refs=excluded_fact_refs,
    ), rag_log


async def run_targeted_evidence(
    dimension_key: str,
    cfg: Any,
    state: Dict[str, Any],
    *,
    query: str,
    required_facts: list[str] | None = None,
) -> tuple[str, list[dict[str, Any]]]:
    """Run a bounded follow-up through the unified evidence router.

    L1 repair passes reuse the same REPORT/KG/BUNDLE/LOCAL_TEXT/RAG adapters as
    the normal dimension retrieval.  The result is context only; source-row
    canonical values and spatial authority remain owned by L1/GROUND.
    """

    from app.contracts.evidence.evidence_contracts import ExplorationRequest
    from app.infrastructure.evidence_runtime.facade import retrieve_evidence

    session_id = str(state.get("session_id", "") or "")
    config = state.get("config") or {}
    context = await _current_planning_context(state)
    from app.modules.l1.dimension_contracts import get_dimension_entity_scope

    entity_scope = get_dimension_entity_scope(dimension_key, cfg)
    if not entity_scope:
        raise ValueError(f"No retrieval entity scope configured for {dimension_key!r}")
    project_cognition_scope = _project_cognition_scope(
        context,
        state,
        entity_scope,
    )
    from app.infrastructure.context_runtime.projection_builder import build_project_cognition

    project_cognition = build_project_cognition(context, project_cognition_scope)
    request = ExplorationRequest(
        run_id=f"{session_id}:{dimension_key}:l1-followup",
        request_type="fact_check",
        query=str(query or "").strip(),
        context_refs=[],
        stage=f"L{getattr(cfg, 'layer', 1)}",
        dimension_key=dimension_key,
        query_purpose="fact_check",
        required_facts=list(required_facts or []),
        entity_scope=entity_scope,
        project_cognition_digest=project_cognition.cognition_digest,
        project_scope=project_cognition.spatial_scope,
    )
    world_model_mode = str(
        getattr(context, "world_model_mode", "off") or "off"
    ).strip().lower()
    v2_mode = world_model_mode in {"prefer_v2", "v2_only"}
    shadow_mode = world_model_mode == "shadow"
    try:
        if (v2_mode or shadow_mode) and getattr(context, "data_resource_catalog", None) is not None:
            from app.contracts.evidence.requirement_contracts import EvidenceRequirement
            from app.modules.evidence.application import EvidenceApplication, EvidenceContext

            requirement = EvidenceRequirement(
                requirement_id=f"{session_id}:{dimension_key}:followup",
                request_id=request.run_id,
                producer_stage=request.stage or "L1",
                statement=request.query,
                kind="spatial" if entity_scope else "claim",
                scope=tuple(entity_scope),
                spatial_granularity="feature" if entity_scope else "none",
                allowed_inference="exact",
                evidence_role="dimension_followup",
            )
            v2_result = await EvidenceApplication().retrieve(
                requirement,
                EvidenceContext.from_runtime_context(
                    context,
                    session_id=session_id,
                    run_id=request.run_id,
                    stage=request.stage,
                    dimension_key=dimension_key,
                    purpose="fact_check",
                    request_type=request.request_type,
                    context_refs=tuple(request.context_refs),
                ),
                candidate_limit=32,
            )
            if shadow_mode:
                legacy_result = await retrieve_evidence(
                    request,
                    session_id=session_id,
                    village_name=str(
                        getattr(context, "village_name", "")
                        or config.get("village_name", "")
                        or ""
                    ),
                )
                result = legacy_result
                try:
                    from app.infrastructure.cognition_runtime.shadow_compare import record_shadow_stage

                    record_shadow_stage(
                        session_id=session_id,
                        stage=request.stage or "L1",
                        dimension_key=dimension_key,
                        v1_refs=getattr(getattr(legacy_result, "evidence_packet", None), "candidate_refs", ()) or (),
                        v2_refs=getattr(getattr(v2_result, "evidence_packet", None), "candidate_refs", ()) or (),
                        details="shadow targeted evidence; legacy result returned",
                        v1_available=getattr(legacy_result, "evidence_packet", None) is not None,
                        v2_available=getattr(v2_result, "evidence_packet", None) is not None,
                    )
                except Exception as exc:
                    logger.debug("[dimension_runtime] shadow targeted diff failed: %s", exc)
            else:
                result = v2_result
        else:
            result = await retrieve_evidence(
                request,
                session_id=session_id,
                village_name=str(
                    getattr(context, "village_name", "")
                    or config.get("village_name", "")
                    or ""
                ),
            )
        trace: list[dict[str, Any]] = []
        if result.evidence_packet is not None:
            trace = [
                item for item in result.evidence_packet.query_trace
                if isinstance(item, dict)
            ][-12:]
        # Query traces explain how the router ran; they do not by themselves
        # preserve the exact evidence locator that the repair pass saw.  Keep
        # a bounded, typed projection beside the trace so the L1 artifact can
        # replay the evidence/fact → source/span relationship without
        # treating retrieved prose as canonical input data.
        trace.append({
            "step": "l1_followup_evidence",
            "status": "returned" if result.evidence_bundle.facts else "empty",
            "fact_count": len(result.evidence_bundle.facts),
            "source_count": len(result.evidence_bundle.sources),
            "facts": [
                {
                    "statement": fact.statement[:600],
                    "source_refs": list(fact.source_refs or [])[:8],
                    "spatial_refs": list(fact.spatial_refs or [])[:8],
                    "evidence_span": fact.evidence_span[:1200],
                    "source_locator": fact.source_locator,
                    "feature_bsm": fact.feature_bsm,
                    "related_parcel_bsms": list(fact.related_parcel_bsms or [])[:8],
                }
                for fact in result.evidence_bundle.facts[:24]
            ],
            "sources": [
                {
                    "source_type": source.source_type,
                    "reference": source.reference,
                    "snapshot_ref": source.snapshot_ref,
                    "authority": source.authority,
                    "evidence_role": source.evidence_role,
                }
                for source in result.evidence_bundle.sources[:24]
            ],
            "unresolved": list(result.evidence_bundle.unresolved or [])[:16],
        })
        return _analysis_evidence_context(result), trace
    except Exception as exc:  # noqa: BLE001 - repair remains bounded
        return "", [{
            "step": "l1_followup_retrieval",
            "status": "failed",
            "error_code": type(exc).__name__,
        }]


async def publish_dimension_start(
    session_id: str,
    dimension_key: str,
    dimension_name: str,
    layer: int,
    is_revision: bool,
) -> None:
    """Publish DIMENSION_START SSE event."""
    from app.infrastructure.events import event_hub as sse_manager

    await sse_manager.publish(session_id, {
        "type": SSEEventType.DIMENSION_START,
        "dimension_key": dimension_key,
        "dimension_name": dimension_name,
        "layer": layer,
        "is_revision": is_revision,
    })


async def publish_dimension_delta(
    session_id: str,
    dimension_key: str,
    dimension_name: str,
    layer: int,
    is_revision: bool,
    delta: str,
    accumulated: str,
) -> None:
    """Publish a single DIMENSION_DELTA SSE event (throttling handled by caller)."""
    from app.infrastructure.events import event_hub as sse_manager

    await sse_manager.publish(session_id, {
        "type": SSEEventType.DIMENSION_DELTA,
        "dimension_key": dimension_key,
        "dimension_name": dimension_name,
        "layer": layer,
        "delta": delta,
        "accumulated": accumulated,
        "is_revision": is_revision,
    })


async def publish_dimension_complete(
    session_id: str,
    dimension_key: str,
    dimension_name: str,
    word_count: int,
    structured_summary: Any,
    report_id: str,
    version: int,
    layer: int,
    is_revision: bool,
) -> None:
    """Publish a typed display-summary projection without reparsing text."""
    from app.infrastructure.events import event_hub as sse_manager

    structured_summary_obj = _validated_summary_projection(
        structured_summary,
        dimension_key=dimension_key,
        layer=layer,
    )

    await sse_manager.publish(session_id, {
        "type": SSEEventType.DIMENSION_COMPLETE,
        "dimension_key": dimension_key,
        "dimension_name": dimension_name,
        "word_count": word_count,
        "structured_summary": structured_summary_obj,
        "report_id": report_id,
        "version": version,
        "layer": layer,
        "is_revision": is_revision,
    })


def _validated_summary_projection(
    structured_summary: Any,
    *,
    dimension_key: str,
    layer: int,
) -> Optional[Dict[str, Any]]:
    """Return one schema-validated display projection, or ``None``.

    The complete event is a presentation projection, not a second semantic
    parser.  Only the already-typed derived-summary model is accepted here;
    arbitrary mappings that merely carry an authority marker are rejected.
    """

    from pydantic import BaseModel

    if not isinstance(structured_summary, BaseModel):
        return None

    candidate = structured_summary.model_dump(mode="python")
    if not isinstance(candidate, dict):
        return None

    try:
        from app.data.ingestion.summary_generator import derived_summary_schema

        validated = derived_summary_schema(dimension_key).model_validate(
            candidate,
            extra="forbid",
        )
    except (KeyError, TypeError, ValueError):
        return None

    if (
        validated.authority != "derived_summary"
        or validated.dimension_key != dimension_key
        or validated.layer != layer
    ):
        return None
    return validated.model_dump(mode="json")


async def save_report_immediate(store: Any, pending_report: Dict[str, Any]) -> bool:
    """Save a report before completion is exposed to parallel consumers."""
    dim_key = pending_report.get("dimension_key", "?")
    next_version = pending_report.get("version", "?")
    try:
        await store.bulk_save([pending_report])
        logger.info(f"[dimension_runtime] {dim_key}: Report saved to DB immediately (v{next_version})")
        return True
    except Exception as e:
        logger.warning(f"[dimension_runtime] {dim_key}: Immediate DB save failed: {e}")
        return False


async def save_step_report(
    session_id: str,
    stage: str,
    step_name: str,
    dimension_key: str,
    layer: int,
    *,
    is_revision: bool = False,
    inputs: Optional[Dict[str, Any]] = None,
    outputs: Optional[Dict[str, Any]] = None,
    diagnostics: Optional[Dict[str, Any]] = None,
) -> None:
    """Save a StepReport. Non-fatal on error."""
    from app.infrastructure.reports.step_report import save_step_report as _save_step_report

    merged_inputs = {"is_revision": is_revision}
    if inputs:
        merged_inputs.update(inputs)
    try:
        await _save_step_report(
            session_id, stage,
            step_name=step_name,
            dimension_key=dimension_key,
            layer=layer,
            inputs=merged_inputs,
            outputs=outputs,
            diagnostics=diagnostics,
        )
    except Exception as e:
        logger.debug(f"[dimension_runtime] {dimension_key}: step report failed: {e}")


async def generate_summary(
    dimension_key: str,
    dim_layer: int,
    content: str,
    *,
    source_artifact: Any,
) -> str:
    """Generate a typed summary and serialize it at the storage boundary."""
    from app.data.ingestion.summary_generator import generate_summary_model

    summary = await generate_summary_model(
        dimension_key,
        dim_layer,
        content,
        source_artifact=source_artifact,
    )
    return summary.model_dump_json(ensure_ascii=False)


__all__ = [
    "RetrievedChunk",
    "RAGRetrievalLog",
    "is_provider_quota_exhausted",
    "run_rag",
    "run_targeted_evidence",
    "strip_model_reasoning",
    "publish_dimension_start",
    "publish_dimension_delta",
    "publish_dimension_complete",
    "save_report_immediate",
    "save_step_report",
    "generate_summary",
]
