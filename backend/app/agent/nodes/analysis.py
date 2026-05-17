"""
维度分析节点 - 简化版

直接执行维度分析，无需中间 executor 层。
"""

import asyncio
import time
from dataclasses import dataclass, asdict
from datetime import datetime
from enum import Enum
from typing import Dict, Any, List, Optional
from langchain_core.messages import AIMessage

from ...config import get_dimension_config, get_dimension_layer, list_dimensions
from ...core.llm import create_llm
from ...core.settings import LLM_MODEL, MAX_TOKENS
from app.utils.logger import get_logger

logger = get_logger(__name__)


# ============================================
# RAG Retrieval Logging
# ============================================

@dataclass
class RetrievedChunk:
    """单个检索到的切片"""
    chunk_id: str
    content_preview: str  # 切片内容
    source: str
    score: float
    dimension_tags: List[str]


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


# Cached LLM instance — reused across all dimension analyses
_llm_cache: Optional[Any] = None


def _get_llm():
    global _llm_cache
    if _llm_cache is None:
        _llm_cache = create_llm(model=LLM_MODEL, temperature=0.7, max_tokens=MAX_TOKENS, streaming=True)
    return _llm_cache


class ParamSource(str, Enum):
    """工具参数来源"""
    LITERAL = "literal"
    GIS_CACHE = "gis_cache"
    CONFIG = "config"
    CONTEXT = "context"


# 维度名称映射
DIMENSION_NAMES = {dim.key: dim.name for dim in list_dimensions()}


def get_layer_from_dimension(dimension_key: str) -> int:
    layer = get_dimension_layer(dimension_key)
    return layer if layer is not None else 3


def create_dimension_state(dimension_key: str, parent_state: Dict[str, Any]) -> Dict[str, Any]:
    """创建维度状态（Send API 用）"""
    layer = get_dimension_layer(dimension_key) or 3
    return {
        "dimension_key": dimension_key,
        "dimension_name": DIMENSION_NAMES.get(dimension_key, dimension_key),
        "session_id": parent_state.get("session_id", ""),
        "project_name": parent_state.get("project_name", ""),
        "config": parent_state.get("config", {}),
        "image_ids": parent_state.get("image_ids", []) if layer == 1 else [],
        "completed_dimensions": parent_state.get("completed_dimensions", {}),
    }


async def analyze_dimension(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    维度分析节点 - 直接执行

    流程：
    1. 获取配置
    2. 并行 GIS 工具
    3. RAG 查询
    4. 组装 Prompt
    5. 流式 LLM + SSE
    6. 保存版本
    7. 返回状态更新
    """
    from ...services import GisService, RagService
    from ...services.sse import sse_manager
    from ...services.report_store import ReportStore

    dim_key = state.get("dimension_key")
    if not dim_key:
        return {"messages": [AIMessage(content="[执行失败] 缺少维度标识")]}

    session_id = state.get("session_id", "")
    phase = state.get("phase", "layer1")
    logger.info(f"[analyze_dimension] {dim_key} (phase={phase})")

    # 1. 获取配置
    cfg = get_dimension_config(dim_key)
    if not cfg:
        return {"messages": [AIMessage(content=f"[执行失败] 配置缺失: {dim_key}")]}

    dim_name = getattr(cfg, 'name', dim_key)
    dim_layer = getattr(cfg, 'layer', get_dimension_layer(dim_key) or 3)

    # 2. 并行 GIS 工具
    tool_results = []
    tools = getattr(cfg, 'tools', [])
    if tools:
        context = {
            "session_id": session_id,
            "project_name": state.get("project_name", ""),
            "village_data": state.get("config", {}).get("village_data", ""),
        }
        tool_results = await GisService.run_parallel(tools, context)

    # 3. RAG query (three-level switch: Layer > Session > Dimension)
    rag_context = ""
    config = state.get("config", {})
    rag_log = None  # RAG检索日志

    # Layer-level switch (highest priority)
    rag_layer_config = config.get("rag_layer_config", {})
    layer_rag_enabled = rag_layer_config.get(dim_layer, True)

    # Session-level switch (backward compatible)
    global_rag_enabled = config.get("rag_enabled", True)

    # Dimension-level switch
    dim_rag_query = getattr(cfg, 'rag_query', '')

    # Combined decision: Layer && Session && Dimension
    rag_enabled = layer_rag_enabled and global_rag_enabled

    if rag_enabled and dim_rag_query:
        start_time = time.time()
        try:
            # 生成多条查询
            queries = await RagService.get_instance().generate_queries(cfg, state)
            query_method = "llm_multi"

            # 并行执行所有查询（每条查询取更多结果，后续去重）
            search_tasks = [RagService.get_instance().search(query, top_k=5) for query in queries]
            all_results_nested = await asyncio.gather(*search_tasks)
            all_results = [r for results in all_results_nested for r in results]

            # 去重并排序（按 score，L2距离越小越相似）
            seen_content = set()
            unique_results = []
            for r in sorted(all_results, key=lambda x: x.get("score", 999)):
                content_key = r.get("content", "")[:100]
                if content_key not in seen_content:
                    seen_content.add(content_key)
                    unique_results.append(r)

            # 取 top-k
            results = unique_results[:5]

            # 计算延迟
            latency_ms = (time.time() - start_time) * 1000

            # 构建检索日志
            retrieved_chunks = []
            for r in results:
                chunk = RetrievedChunk(
                    chunk_id=str(hash(r.get("content", "")[:100])),
                    content_preview=r.get("content", ""),
                    source=r.get("metadata", {}).get("source", "unknown"),
                    score=r.get("score", 0.0),
                    dimension_tags=r.get("metadata", {}).get("dimension_tags", []),
                )
                retrieved_chunks.append(chunk)

            # 格式化上下文
            rag_context = RagService.format_for_prompt(results)

            rag_log = RAGRetrievalLog(
                dimension_key=dim_key,
                query=queries[0] if queries else "",
                query_generation_method=query_method,
                retrieved_chunks=retrieved_chunks,
                total_results=len(results),
                retrieval_latency_ms=latency_ms,
                context_length=len(rag_context),
                context_truncated=len(rag_context) > 1500,
                rag_enabled=True,
                skip_reason="",
            )

            # Send rag_result SSE event for frontend knowledge panel (always send to clear old data)
            from ...services.sse import sse_manager
            await sse_manager.publish(session_id, {
                "type": "rag_result",
                "dimension_key": dim_key,
                "layer": dim_layer,
                "query": queries[0] if queries else "",
                "query_generation_method": query_method,
                "retrieval_latency_ms": latency_ms,
                "total_results": len(results),
                "documents": [
                    {
                        "title": r.get("metadata", {}).get("source", "unknown"),
                        "snippet": r.get("content", ""),
                        "source": r.get("metadata", {}).get("source"),
                        "score": r.get("score", 0.0),
                    }
                    for r in results
                ],
            })
            logger.info(f"[analyze_dimension] {dim_key}: Sent rag_result SSE event with {len(results)} documents")

            if rag_context:
                logger.info(f"[analyze_dimension] {dim_key}: RAG retrieved {len(rag_context)} chars, {len(results)} chunks, {latency_ms:.1f}ms")
            else:
                logger.info(f"[analyze_dimension] {dim_key}: RAG no results, {latency_ms:.1f}ms")

        except Exception as e:
            logger.error(f"[analyze_dimension] {dim_key}: RAG error: {e}")
            rag_log = RAGRetrievalLog(
                dimension_key=dim_key,
                query="",
                query_generation_method="error",
                retrieved_chunks=[],
                total_results=0,
                retrieval_latency_ms=0,
                context_length=0,
                context_truncated=False,
                rag_enabled=True,
                skip_reason=f"Error: {str(e)}",
            )

            # Send empty rag_result SSE event to clear old data on frontend
            from ...services.sse import sse_manager
            await sse_manager.publish(session_id, {
                "type": "rag_result",
                "dimension_key": dim_key,
                "layer": dim_layer,
                "query": "",
                "query_generation_method": "error",
                "retrieval_latency_ms": 0,
                "total_results": 0,
                "documents": [],
            })
            logger.info(f"[analyze_dimension] {dim_key}: Sent empty rag_result SSE event (RAG error)")
    else:
        reasons = []
        if not layer_rag_enabled:
            reasons.append(f"Layer{dim_layer} RAG disabled")
        if not global_rag_enabled:
            reasons.append("Session RAG disabled")
        if not dim_rag_query:
            reasons.append("Dimension rag_query empty")
        skip_reason = ', '.join(reasons)
        logger.info(f"[analyze_dimension] {dim_key}: Skipped RAG ({skip_reason})")

        rag_log = RAGRetrievalLog(
            dimension_key=dim_key,
            query="",
            query_generation_method="skipped",
            retrieved_chunks=[],
            total_results=0,
            retrieval_latency_ms=0,
            context_length=0,
            context_truncated=False,
            rag_enabled=False,
            skip_reason=skip_reason,
        )

        # Send empty rag_result SSE event to clear old data on frontend
        from ...services.sse import sse_manager
        await sse_manager.publish(session_id, {
            "type": "rag_result",
            "dimension_key": dim_key,
            "layer": dim_layer,
            "query": "",
            "query_generation_method": "skipped",
            "retrieval_latency_ms": 0,
            "total_results": 0,
            "documents": [],
        })
        logger.info(f"[analyze_dimension] {dim_key}: Sent empty rag_result SSE event (RAG skipped)")

    # 4. 从数据库加载依赖报告（按配置过滤）
    store = ReportStore.get_instance()
    deps = ""
    same_layer_contexts = ""

    # 同层依赖加载 - 添加等待机制解决竞态条件
    # LangGraph Send API 的 state 快照可能过时，导致下游维度启动时上游报告尚未保存
    same_layer_deps = getattr(cfg, 'depends_on', [])
    if same_layer_deps:
        layer_reports = await store.get_layer_reports(session_id, dim_layer)
        contexts = []
        missing_deps = []

        # 等待依赖报告可用（最多等待 120 秒）
        max_wait_seconds = 120
        check_interval = 2

        for dep_key in same_layer_deps:
            if dep_key in layer_reports and layer_reports[dep_key]:
                contexts.append(f"【{dep_key}】分析结果：\n{layer_reports[dep_key]}")
            else:
                # 等待依赖报告保存完成
                waited = 0
                report = None
                while waited < max_wait_seconds:
                    await asyncio.sleep(check_interval)
                    waited += check_interval
                    report = await store.get_latest(session_id, dep_key)
                    if report:
                        contexts.append(f"【{dep_key}】分析结果：\n{report}")
                        logger.info(f"[analyze_dimension] {dim_key}: 等待 {waited}s 后获取到依赖 {dep_key}")
                        break

                if not report:
                    missing_deps.append(dep_key)

        if missing_deps:
            logger.error(f"[analyze_dimension] {dim_key}: 依赖报告加载失败（等待{max_wait_seconds}s后）: {missing_deps}")
            raise DependencyError(f"维度 {dim_key} 的依赖报告加载失败: {missing_deps}")

        same_layer_contexts = "\n\n".join(contexts)
        logger.info(f"[analyze_dimension] {dim_key}: 加载同层依赖 {len(same_layer_deps)} 个")

    # 跨层依赖加载（按配置过滤）
    if dim_layer == 2:
        # Layer 2 依赖 Layer 1 报告（按 layer_depends_on 配置）
        layer1_deps = getattr(cfg, 'layer_depends_on', [])
        layer1_reports = await store.get_layer_reports(session_id, 1)
        if layer1_deps:
            deps = "\n".join([f"【{k}】{layer1_reports.get(k, '')}" for k in layer1_deps if layer1_reports.get(k)])
        else:
            deps = "\n".join([f"【{k}】{v}" for k, v in layer1_reports.items() if v])
        logger.info(f"[analyze_dimension] {dim_key}: 加载跨层依赖 {len(layer1_deps) if layer1_deps else len(layer1_reports)} 个")

    elif dim_layer == 3:
        # Layer 3 依赖 Layer 1 和 Layer 2（按配置过滤）
        layer1_deps = getattr(cfg, 'layer_depends_on', [])
        layer2_deps = getattr(cfg, 'phase_depends_on', [])
        layer1_reports, layer2_reports = await asyncio.gather(
            store.get_layer_reports(session_id, 1),
            store.get_layer_reports(session_id, 2),
        )
        deps_parts = []
        for k in layer1_deps:
            if layer1_reports.get(k):
                deps_parts.append(f"【{k}】{layer1_reports[k]}")
        for k in layer2_deps:
            if layer2_reports.get(k):
                deps_parts.append(f"【{k}】{layer2_reports[k]}")
        deps = "\n".join(deps_parts)
        logger.info(f"[analyze_dimension] {dim_key}: 加载跨层依赖 L1={len(layer1_deps)} L2={len(layer2_deps)} 个")

    # 5. 组装 Prompt
    prompt = _build_prompt(cfg, state, tool_results, rag_context, deps, same_layer_contexts)

    # 6. 流式 LLM + SSE
    llm = _get_llm()

    llm_response = ""
    await sse_manager.publish(session_id, {
        "type": "dimension_start",
        "dimension_key": dim_key,
        "dimension_name": dim_name,
        "layer": dim_layer,
    })

    try:
        async for chunk in llm.astream(prompt):
            if hasattr(chunk, 'content') and chunk.content:
                llm_response += chunk.content
                await sse_manager.publish(session_id, {
                    "type": "dimension_delta",
                    "dimension_key": dim_key,
                    "dimension_name": dim_name,
                    "layer": dim_layer,
                    "delta": chunk.content,
                    "accumulated": llm_response,
                })
    except Exception as e:
        logger.error(f"[analyze_dimension] LLM 失败: {e}")
        return {"messages": [AIMessage(content=f"[执行失败] LLM错误: {e}")]}

    # 7. 保存版本
    current_versions = state.get("report_versions", {}).get(dim_key, [])
    next_version = len(current_versions) + 1
    revision_reason = state.get("feedback")

    # Format GIS data for storage
    gis_data_list = []
    for r in tool_results:
        if r and getattr(r, 'success', False):
            gis_data_list.append({
                "tool": getattr(r, 'tool_name', 'unknown'),
                "data": getattr(r, 'data', None),
            })

    report_id = await store.save(
        session_id=session_id,
        dim_key=dim_key,
        version=next_version,
        content=llm_response,
        metadata={"revision_reason": revision_reason},
        layer=dim_layer,
        knowledge_sources=asdict(rag_log) if rag_log and rag_log.rag_enabled else None,
        gis_data=gis_data_list if gis_data_list else None,
    )

    # 8. 发送完成事件 (含 GIS 数据)
    await sse_manager.publish(session_id, {
        "type": "dimension_complete",
        "dimension_key": dim_key,
        "dimension_name": dim_name,
        "word_count": len(llm_response),  # 仅传递元数据，内容已通过 dimension_delta 累积
        "report_id": report_id,
        "version": next_version,
        "gis_data": gis_data_list,
        "layer": dim_layer,
    })

    # 9. 状态更新 - 仅返回增量，reducer 负责合并
    phase_key = f"layer{dim_layer}"

    return {
        "messages": [AIMessage(content=llm_response, metadata={"dimension_key": dim_key})],
        "completed_dimensions": {phase_key: [dim_key]},
    }


def _build_prompt(cfg, state, tool_results, rag_context, deps: str = "", same_layer_contexts: str = "") -> str:
    """组装 Prompt - 使用 prompts 模块模板

    Args:
        cfg: 维度配置
        state: 当前状态
        tool_results: GIS 工具结果
        rag_context: RAG 检索上下文
        deps: 前序依赖报告（从数据库加载）
        same_layer_contexts: 同层依赖报告
    """
    from ...services.modules.prompts.analysis import get_dimension_prompt as get_layer1_prompt
    from ...services.modules.prompts.concept import get_dimension_prompt as get_layer2_prompt
    from ...services.modules.prompts.detailed import get_dimension_prompt as get_layer3_prompt

    dim_key = getattr(cfg, 'key', state.get("dimension_key", ""))
    layer = getattr(cfg, 'layer', get_dimension_layer(dim_key) or 1)
    dim_name = getattr(cfg, 'name', DIMENSION_NAMES.get(dim_key, dim_key))

    project_name = state.get("project_name", "村庄")
    village_data = state.get("config", {}).get("village_data", "")
    task_desc = state.get("config", {}).get("task_description", "制定村庄发展规划")
    constraints = state.get("config", {}).get("constraints", "无特殊约束")

    # GIS 工具数据
    tool_section = ""
    for r in tool_results:
        if r and getattr(r, 'success', False):
            tool_section += f"\n【GIS数据】\n{str(getattr(r, 'data', r))[:1000]}\n"

    # 根据层级选择 Prompt 模板
    if layer == 1:
        return get_layer1_prompt(
            dimension_key=dim_key,
            raw_data=village_data + tool_section,
            village_name=project_name,
            task_description=task_desc,
            constraints=constraints,
            knowledge_context=rag_context or "",
            has_images=bool(state.get("image_ids")),
        )
    elif layer == 2:
        return get_layer2_prompt(
            dimension_key=dim_key,
            analysis_report=deps,
            task_description=task_desc,
            constraints=constraints,
            knowledge_context=rag_context or "",
            layer2_contexts=same_layer_contexts,  # 传递同层依赖报告
        )
    elif layer == 3:
        return get_layer3_prompt(
            dimension_key=dim_key,
            project_name=project_name,
            analysis_report=deps,
            planning_concept=deps,  # 使用相同的依赖报告
            constraints=constraints,
            knowledge_context=rag_context or "",
            professional_data_section=tool_section,
        )

    # 默认通用模板
    return f"""请对 "{project_name}" 进行 {dim_name} 分析。

## 基础数据
{village_data[:2000]}

## 规划任务
{task_desc}

{tool_section}

{deps}

{rag_context if rag_context else ""}

请生成完整的分析报告："""


__all__ = [
    "analyze_dimension",
    "create_dimension_state",
    "DIMENSION_NAMES",
    "get_layer_from_dimension",
    "ParamSource",
]