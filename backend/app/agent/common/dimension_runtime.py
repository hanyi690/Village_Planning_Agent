"""Shared dimension runtime infrastructure for L1/L2/L3 analysis nodes.

Extracted from ``app.agent.l1_observe.analysis_node.analyze_dimension``
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
import json
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from app.config import get_dimension_layer
from app.core.events import SSEEventType
from app.utils.logger import get_logger

logger = get_logger(__name__)


def _display_report(content: str | None) -> str:
    """Return dependency report prose without the private INSTRUCTION block."""
    if not content:
        return ""
    from app.services.report_store import split_instruction

    display, _ = split_instruction(content)
    return display


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


async def run_rag(dimension_key: str, cfg: Any, state: Dict[str, Any]) -> tuple[str, Any | None]:
    """Run RAG retrieval for a dimension. Returns (context_str, RAGRetrievalLog|None).

    Re-reads live config from the checkpoint so PATCH updates to
    rag_layer_config are visible even though Send freezes state at dispatch.
    """
    from app.services.runtime import PlanningRuntimeService

    session_id = state.get("session_id", "")
    config = state.get("config", {})
    dim_layer = getattr(cfg, "layer", get_dimension_layer(dimension_key) or 3)
    prefer_doc_types = getattr(cfg, "prefer_doc_types", None) or None

    _latest = await PlanningRuntimeService.aget_state_values(session_id)
    live_config = _latest.get("config", {}) if _latest else config

    rag_layer_config = live_config.get("rag_layer_config", {})
    layer_rag_enabled = rag_layer_config.get(dim_layer, True)
    global_rag_enabled = live_config.get("rag_enabled", True)
    dim_rag_query = getattr(cfg, "rag_query", "")
    rag_enabled = layer_rag_enabled and global_rag_enabled

    if not rag_enabled or not dim_rag_query:
        return ("", None)

    from app.services.sse import sse_manager
    from app.services import RagService

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
        queries = await RagService.get_instance().generate_queries(cfg, state)
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

        search_tasks = [RagService.get_instance().search(q, top_k=5, prefer_doc_types=prefer_doc_types) for q, _ in uncached_queries]

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
        logger.error(f"[dimension_runtime] {dimension_key}: RAG failed: {e}")
        rlog = RAGRetrievalLog(
            dimension_key=dimension_key, query="", query_generation_method="failed",
            retrieved_chunks=[], total_results=0, retrieval_latency_ms=0,
            context_length=0, context_truncated=False, rag_enabled=False, skip_reason=str(e),
        )
        return ("", rlog)


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
    from app.services.report_store import ReportStore

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
    from app.services.report_store import ReportStore

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
    from app.services.sse import sse_manager

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
    from app.services.sse import sse_manager

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
    structured_summary: str,
    report_id: str,
    version: int,
    layer: int,
    is_revision: bool,
) -> None:
    """Publish DIMENSION_COMPLETE SSE event (parses structured_summary JSON)."""
    from app.services.sse import sse_manager

    try:
        structured_summary_obj = json.loads(structured_summary) if structured_summary else None
    except json.JSONDecodeError:
        structured_summary_obj = None

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


async def save_report_immediate(store: Any, pending_report: Dict[str, Any]) -> None:
    """Immediate DB save of a report so parallel nodes can read it. Non-fatal on error."""
    dim_key = pending_report.get("dimension_key", "?")
    next_version = pending_report.get("version", "?")
    try:
        await store.bulk_save([pending_report])
        logger.info(f"[dimension_runtime] {dim_key}: Report saved to DB immediately (v{next_version})")
    except Exception as e:
        logger.warning(f"[dimension_runtime] {dim_key}: Immediate DB save failed (will retry in completion): {e}")


async def save_step_report(
    session_id: str,
    stage: str,
    step_name: str,
    dimension_key: str,
    layer: int,
    *,
    is_revision: bool = False,
    outputs: Optional[Dict[str, Any]] = None,
    diagnostics: Optional[Dict[str, Any]] = None,
) -> None:
    """Save a StepReport. Non-fatal on error."""
    from app.services.step_report import save_step_report as _save_step_report

    inputs = {"is_revision": is_revision}
    try:
        await _save_step_report(
            session_id, stage,
            step_name=step_name,
            dimension_key=dimension_key,
            layer=layer,
            inputs=inputs,
            outputs=outputs,
            diagnostics=diagnostics,
        )
    except Exception as e:
        logger.debug(f"[dimension_runtime] {dimension_key}: step report failed: {e}")


async def generate_summary(dimension_key: str, dim_layer: int, content: str) -> str:
    """Generate structured summary JSON string with fallback."""
    from app.modules.parsing.summary_generator import generate_structured_summary

    try:
        return await generate_structured_summary(dimension_key, dim_layer, content)
    except Exception as e:
        logger.warning(f"[dimension_runtime] {dimension_key}: Summary generation failed: {e}")
        from app.modules.parsing.schemas import BaseDimensionSummary

        fallback = BaseDimensionSummary(
            dimension_key=dimension_key, layer=dim_layer,
            word_count=len(content), text_summary=content[:200],
        )
        return fallback.model_dump_json(ensure_ascii=False)


def generate_summary_regex(dimension_key: str, dim_layer: int, content: str) -> str:
    """Layer-1 only: deterministic regex extraction (zero LLM, instant).

    Returns the BaseDimensionSummary JSON used for the immediate DB write;
    the Flash-LLM enrichment happens later in the background task.
    """
    from app.modules.parsing.schemas import BaseDimensionSummary
    from app.modules.parsing.summary_generator import (
        _extract_dimension_metrics,
        _extract_key_points_regex,
        _extract_metrics_regex,
    )

    if not content:
        return BaseDimensionSummary(
            dimension_key=dimension_key,
            layer=dim_layer,
            word_count=0,
            text_summary="",
            metrics={},
        ).model_dump_json(ensure_ascii=False)

    regex_metrics = _extract_metrics_regex(content)
    dimension_metrics = _extract_dimension_metrics(dimension_key, content)
    metrics = {**regex_metrics, **dimension_metrics}
    key_points = _extract_key_points_regex(content)
    summary = BaseDimensionSummary(
        dimension_key=dimension_key,
        layer=dim_layer,
        word_count=len(content),
        key_points=key_points[:5],
        text_summary=content[:200],
        metrics=metrics,
    )
    return summary.model_dump_json(ensure_ascii=False)


async def enrich_summary_background(
    dimension_key: str,
    dim_layer: int,
    content: str,
    session_id: str,
    version: int,
) -> None:
    """Background task: Flash-LLM summary enrichment + DB update. Non-fatal."""
    try:
        from app.modules.parsing.summary_generator import generate_structured_summary

        summary = await generate_structured_summary(dimension_key, dim_layer, content)
        if not summary:
            return
        from app.services.report_store import ReportStore

        store = ReportStore.get_instance()
        await store.update_summary(session_id, dimension_key, version, summary)
    except Exception as e:
        logger.warning(f"[dimension_runtime] background summary enrich failed for {dimension_key}: {e}")


__all__ = [
    "RetrievedChunk",
    "RAGRetrievalLog",
    "DependencyError",
    "run_rag",
    "load_dependency_reports",
    "load_layered_dependency_reports",
    "publish_dimension_start",
    "publish_dimension_delta",
    "publish_dimension_complete",
    "save_report_immediate",
    "save_step_report",
    "generate_summary",
    "generate_summary_regex",
    "enrich_summary_background",
]
