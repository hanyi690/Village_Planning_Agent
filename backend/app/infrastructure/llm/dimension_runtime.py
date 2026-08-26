"""Shared dimension runtime infrastructure for L1/L2/L3 analysis nodes.

Extracted from ``app.domain.assessment.analysis_node.analyze_dimension``
(Wave D) so the new L2 strategize worker can reuse RAG retrieval,
dependency report loading, SSE publishing, ReportStore save, StepReport
save, and structured summary generation without importing the whole
dimension analysis pipeline.

All helpers are pure wrappers over their I/O dependencies (RagService,
PlanningRuntimeService, sse_manager, ReportStore, step_report service,
summary generator) and are non-fatal where the original L1 code was.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import re
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

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
            try:
                threshold = max(1, int(os.getenv("LLM_PROVIDER_CIRCUIT_FAILURE_THRESHOLD", "3")))
            except (TypeError, ValueError):
                threshold = 3
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
    from app.infrastructure.llm.structured import provider_failure_code

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


def _display_report(content: str | None) -> str:
    """Return dependency report prose (report body; instruction stored separately)."""
    if not content:
        return ""
    return strip_model_reasoning(content)


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


class DependencyError(Exception):
    """依赖缺失异常"""

    pass


async def retrieve_vector_context(dimension_key: str, cfg: Any, state: Dict[str, Any]) -> tuple[str, Any | None]:
    """Run RAG retrieval for a dimension. Returns (context_str, RAGRetrievalLog|None).

    Re-reads live config from the checkpoint so PATCH updates to
    rag_layer_config are visible even though Send freezes state at dispatch.
    """
    from app.infrastructure.runtime.planning_runtime_service import PlanningRuntimeService

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
        ctx = cached.get("context", "")
        logger.info(f"[dimension_runtime] {dimension_key}: RAG cache hit ({len(ctx)} chars)")
        rlog = RAGRetrievalLog(
            dimension_key=dimension_key, query=cached.get("query", ""),
            query_generation_method="cached", retrieved_chunks=[],
            total_results=cached.get("total_results", 0), retrieval_latency_ms=0,
            context_length=len(ctx), context_truncated=False,
            rag_enabled=True, skip_reason="",
        )
        await sse_manager.publish(session_id, {
            "type": SSEEventType.RAG_RESULT, "dimension_key": dimension_key, "layer": dim_layer,
            "query": cached.get("query", ""),
            "query_generation_method": "cached", "retrieval_latency_ms": 0,
            "total_results": cached.get("total_results", 0),
            "documents": cached.get("documents", []),
        })
        return (ctx, rlog)

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

        ctx = RagService.format_for_prompt(results) if results else ""
        rlog = RAGRetrievalLog(
            dimension_key=dimension_key, query=queries[0] if queries else "",
            query_generation_method=query_method, retrieved_chunks=retrieved_chunks,
            total_results=len(results), retrieval_latency_ms=latency_ms,
            context_length=len(ctx), context_truncated=False,
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
            f"[dimension_runtime] {dimension_key}: RAG retrieved {len(ctx)} chars, {len(results)} chunks, {latency_ms:.1f}ms"
        )
        return (ctx, rlog)
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
) -> str:
    """Build the bounded semantic query used by planning workers.

    The query is only a retrieval input.  It does not resolve a name or
    manufacture a spatial identity.  Typed L1 location facts add recall for
    names that are absent from the KG/bundle labels; the EvidenceGraph still
    decides which Bundle feature is authoritative.
    """
    config = state.get("config") or {}
    session_id = str(state.get("session_id", "") or "").strip()
    context = None
    if session_id:
        try:
            from app.infrastructure.context.planning_context_factory import (
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
) -> tuple[str, Any | None]:
    """Compatibility adapter to the unified Explore evidence service.

    The historical vector-RAG implementation remains available only as the
    ``rag`` retriever adapter.  Dimension workers call this one entry point;
    they must not append a second ``retrieve_evidence`` section themselves.
    """
    from app.contracts.evidence.evidence_contracts import ExplorationRequest
    from app.evidence.retrieval.evidence_service import (
        render_evidence_prompt_section,
        retrieve_evidence,
    )

    session_id = str(state.get("session_id", "") or "")
    config = state.get("config") or {}
    external_enabled = str(
        config.get(
            "evidence_external_for_llm",
            os.getenv("EVIDENCE_EXTERNAL_FOR_LLM", "false"),
        )
    ).strip().lower() in {"1", "true", "yes", "on"}
    external_kwargs: dict[str, Any] = {}
    owned_external_provider = False
    context_refs = ["source:rag"]
    if external_enabled:
        # External evidence is deliberately an explicit planning opt-in.  In
        # the normal application path the lifecycle-owned provider is reused;
        # a typed unavailable adapter is used only for an explicit opt-in with
        # no configured provider, so the LLM sees a diagnostic rather than a
        # silent omission.  Neither path creates geometry or source identity.
        try:
            from app.application.queries.evidence import (
                build_external_evidence_policy,
                get_active_external_provider,
                get_configured_external_provider,
            )

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
            from app.evidence.retrieval.external_search_policy import ExternalSearchPolicy
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
        query=_planning_evidence_query(dimension_key, cfg, state),
        stage=f"L{getattr(cfg, 'layer', 3)}",
        dimension_key=dimension_key,
        query_purpose="context_injection",
        entity_scope=[
            "parcels", "facilities", "roads", "annotations", "hazards",
            "waters", "zones", "settlements",
        ],
        context_refs=context_refs,
    )
    try:
        result = await retrieve_evidence(
            request,
            session_id=session_id,
            village_name=str(config.get("village_name", "") or ""),
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
    cognition = getattr(result, "spatial_cognition", None)
    coverage = getattr(result, "coverage", None)
    if trace_sink is not None:
        sources = list(getattr(bundle, "sources", None) or [])
        trace_sink.update({
            "source_types": sorted({
                str(getattr(source, "source_type", "") or "").strip()
                for source in sources
                if str(getattr(source, "source_type", "") or "").strip()
            }),
            "fact_count": len(getattr(bundle, "facts", None) or []),
            "kg_confidence": float(
                getattr(cognition, "kg_confidence", 0.0) or 0.0
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
        })
    rag_log = None
    try:
        from app.evidence.retrieval.retrievers.rag_retriever import consume_rag_log

        rag_log = consume_rag_log(session_id, dimension_key)
    except Exception:
        rag_log = None
    # Use the same persisted L1Snapshot that the consuming worker uses to
    # build its fact catalog.  Falling back to the context cache is only for
    # stages that do not yet have an L1 artifact.
    allowed_l1_fact_ids = _current_l1_fact_ids(session_id, state)
    return render_evidence_prompt_section(
        result.evidence_bundle,
        result.spatial_cognition,
        result.evidence_packet,
        result.coverage,
        allowed_l1_fact_ids=allowed_l1_fact_ids,
    ), rag_log


def _current_l1_fact_ids(
    session_id: str,
    state: Dict[str, Any] | None = None,
) -> set[str] | None:
    """Return the current snapshot's selectable L1 IDs, if hydrated.

    Evidence lineage can contain refs from semantic overlays and source
    annotations.  Only IDs present in the same frozen snapshot as the worker
    may be shown in an LLM prompt as L1 lineage.  ``None`` is reserved for a
    context that has no L1 field at all; an explicitly hydrated empty list
    therefore remains an empty closed set.
    """
    try:
        from app.domain.validation.l1_fact_catalog import build_l1_fact_catalog

        artifact_ref = ((state or {}).get("artifact_refs") or {}).get("l1_snapshot")
        if isinstance(artifact_ref, dict):
            try:
                from app.infrastructure.artifacts.runtime import load_artifact

                payload = load_artifact(state or {}, "l1_snapshot")
                if hasattr(payload, "model_dump"):
                    payload = payload.model_dump(mode="json")
                if isinstance(payload, dict) and "fact_records" in payload:
                    return set(
                        build_l1_fact_catalog(payload.get("fact_records") or [])
                        .usable_allowed_fact_ids
                    )
            except Exception:
                # An explicit snapshot reference with an unreadable artifact
                # is an empty closed set, not permission to use cached or
                # lineage-only IDs from another context version.
                return set()
            return set()

        from app.infrastructure.context.planning_context_factory import (
            get_cached_context,
        )

        context = get_cached_context(session_id) if session_id else None
        if context is None or not hasattr(context, "l1_fact_records"):
            return None
        return set(
            build_l1_fact_catalog(
                getattr(context, "l1_fact_records", None) or []
            ).usable_allowed_fact_ids
        )
    except Exception:
        # Prompt rendering remains available when the optional context cache
        # is cold; the evidence graph still applies the same filter whenever
        # its PlanningContext carries the snapshot records.
        return None


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
    from app.evidence.retrieval.evidence_service import (
        render_evidence_prompt_section,
        retrieve_evidence,
    )

    session_id = str(state.get("session_id", "") or "")
    config = state.get("config") or {}
    request = ExplorationRequest(
        run_id=f"{session_id}:{dimension_key}:l1-followup",
        request_type="fact_check",
        query=str(query or "").strip(),
        context_refs=[
            "source:local_text",
            "source:report",
            "source:kg",
            "source:bundle",
            "source:rag",
        ],
        stage=f"L{getattr(cfg, 'layer', 1)}",
        dimension_key=dimension_key,
        query_purpose="fact_check",
        required_facts=list(required_facts or []),
        entity_scope=[
            "parcels", "facilities", "roads", "annotations", "hazards",
            "waters", "zones", "settlements",
        ],
    )
    try:
        result = await retrieve_evidence(
            request,
            session_id=session_id,
            village_name=str(config.get("village_name", "") or ""),
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
        return render_evidence_prompt_section(
            result.evidence_bundle,
            result.spatial_cognition,
            result.evidence_packet,
            result.coverage,
            allowed_l1_fact_ids=_current_l1_fact_ids(session_id, state),
        ), trace
    except Exception as exc:  # noqa: BLE001 - repair remains bounded
        return "", [{
            "step": "l1_followup_retrieval",
            "status": "failed",
            "error_code": type(exc).__name__,
        }]


async def load_dependency_reports(
    dimension_key: str,
    cfg: Any,
    dim_layer: int,
    session_id: str,
    is_revision: bool,
) -> tuple[str, str]:
    """Load same-layer and cross-layer dependency reports.

    Returns (deps, same_layer_contexts). Raises DependencyError when
    same-layer dependencies cannot be recovered from DB + fallback.
    """
    from app.infrastructure.reports.report_store import ReportStore

    store = ReportStore.get_instance()
    deps = ""
    same_layer_contexts = ""

    # 同层依赖加载 - 通过 DB 获取（并行节点无法通过状态快照看到彼此的 pending_reports）
    same_layer_deps = getattr(cfg, "depends_on", [])
    if same_layer_deps:
        contexts = []
        for dep_key in same_layer_deps:
            db_report = await store.get_latest(session_id, dep_key)
            if db_report:
                contexts.append(f"【{dep_key}】分析结果：\n{_display_report(db_report)}")
                continue
            # Fallback: get_latest_report
            dep_report = await store.get_latest_report(session_id, dep_key)
            if dep_report:
                contexts.append(f"【{dep_key}】分析结果：\n{_display_report(dep_report['content'])}")
                continue
            raise DependencyError(
                f"维度 {dimension_key} 的同层依赖 {dep_key} 报告缺失"
                "（_ready_dispatch 应保证依赖已完成，此为调度 bug）"
            )
        same_layer_contexts = "\n\n".join(contexts)
        logger.info(f"[dimension_runtime] {dimension_key}: 加载同层依赖 {len(same_layer_deps)} 个")

    # 跨层依赖加载（按配置过滤）
    if dim_layer == 2:
        # Layer 2 依赖 Layer 1 报告（按 layer_depends_on 配置）
        layer1_deps = getattr(cfg, "layer_depends_on", [])
        layer1_reports = await store.get_layer_reports(session_id, 1)
        if layer1_deps:
            deps = "\n".join([f"【{k}】{_display_report(layer1_reports.get(k, ''))}" for k in layer1_deps if layer1_reports.get(k)])
        else:
            deps = "\n".join([f"【{k}】{_display_report(v)}" for k, v in layer1_reports.items() if v])
        logger.info(f"[dimension_runtime] {dimension_key}: 加载跨层依赖 {len(layer1_deps) if layer1_deps else len(layer1_reports)} 个")

    elif dim_layer == 3:
        # Layer 3 依赖 Layer 1 和 Layer 2（按配置过滤）
        layer1_deps = getattr(cfg, "layer_depends_on", [])
        layer2_deps = getattr(cfg, "phase_depends_on", [])
        # 顺序调用避免 SQLite aiosqlite 连接管理问题
        layer1_reports = await store.get_layer_reports(session_id, 1)
        layer2_reports = await store.get_layer_reports(session_id, 2)
        deps_parts = []
        for k in layer1_deps:
            if layer1_reports.get(k):
                deps_parts.append(f"【{k}】{_display_report(layer1_reports[k])}")
        for k in layer2_deps:
            if layer2_reports.get(k):
                deps_parts.append(f"【{k}】{_display_report(layer2_reports[k])}")
        deps = "\n".join(deps_parts)
        logger.info(f"[dimension_runtime] {dimension_key}: 加载跨层依赖 L1={len(layer1_deps)} L2={len(layer2_deps)} 个")

    return deps, same_layer_contexts


async def load_layered_dependency_reports(
    dimension_key: str,
    cfg: Any,
    dim_layer: int,
    session_id: str,
    is_revision: bool,
) -> tuple[str, str, str]:
    """Load same-layer + split cross-layer dependency reports.

    For L3 the cross-layer deps split into L1 (layer_depends_on) and L2
    (phase_depends_on). Returns (l1_deps, l2_deps, same_layer_contexts).
    For non-L3 layers, l2_deps is "".
    """
    from app.infrastructure.reports.report_store import ReportStore

    store = ReportStore.get_instance()
    same_layer_contexts = ""

    # 同层依赖加载（与 load_dependency_reports 完全一致）
    same_layer_deps = getattr(cfg, "depends_on", [])
    if same_layer_deps:
        contexts = []
        for dep_key in same_layer_deps:
            db_report = await store.get_latest(session_id, dep_key)
            if db_report:
                contexts.append(f"【{dep_key}】分析结果：\n{_display_report(db_report)}")
                continue
            # Fallback: get_latest_report
            dep_report = await store.get_latest_report(session_id, dep_key)
            if dep_report:
                contexts.append(f"【{dep_key}】分析结果：\n{_display_report(dep_report['content'])}")
                continue
            raise DependencyError(
                f"维度 {dimension_key} 的同层依赖 {dep_key} 报告缺失"
                "（_ready_dispatch 应保证依赖已完成，此为调度 bug）"
            )
        same_layer_contexts = "\n\n".join(contexts)
        logger.info(f"[dimension_runtime] {dimension_key}: 加载同层依赖 {len(same_layer_deps)} 个")

    # 跨层依赖加载：L1 (layer_depends_on) 与 L2 (phase_depends_on) 分开返回
    layer1_deps = getattr(cfg, "layer_depends_on", [])
    layer2_deps = getattr(cfg, "phase_depends_on", [])
    l1_deps = ""
    l2_deps = ""
    if layer1_deps:
        # 顺序调用避免 SQLite aiosqlite 连接管理问题
        layer1_reports = await store.get_layer_reports(session_id, 1)
        l1_deps = "\n".join([f"【{k}】{_display_report(layer1_reports.get(k, ''))}" for k in layer1_deps if layer1_reports.get(k)])
    if dim_layer == 3 and layer2_deps:
        layer2_reports = await store.get_layer_reports(session_id, 2)
        l2_deps = "\n".join([f"【{k}】{_display_report(layer2_reports.get(k, ''))}" for k in layer2_deps if layer2_reports.get(k)])
    logger.info(f"[dimension_runtime] {dimension_key}: 加载分层跨层依赖 L1={len(layer1_deps)} L2={len(layer2_deps)} 个")

    return l1_deps, l2_deps, same_layer_contexts


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


async def generate_summary(dimension_key: str, dim_layer: int, content: str) -> str:
    """Generate a typed summary and serialize it at the storage boundary."""
    from app.data.ingestion.summary_generator import generate_summary_model

    summary = await generate_summary_model(dimension_key, dim_layer, content)
    return summary.model_dump_json(ensure_ascii=False)


__all__ = [
    "RetrievedChunk",
    "RAGRetrievalLog",
    "DependencyError",
    "is_provider_quota_exhausted",
    "retrieve_vector_context",
    "run_rag",
    "run_targeted_evidence",
    "load_dependency_reports",
    "load_layered_dependency_reports",
    "strip_model_reasoning",
    "publish_dimension_start",
    "publish_dimension_delta",
    "publish_dimension_complete",
    "save_report_immediate",
    "save_step_report",
    "generate_summary",
]
