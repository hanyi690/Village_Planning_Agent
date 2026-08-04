"""L2 STRATEGIZE dimension worker - analyze_l2_dimension.

Independent L2-only dimension analysis worker (Wave D). Mirrors the shared
L1 dimension flow but is restricted to the L2 planning-strategy layer and
reuses the shared runtime helpers from ``app.agent.common.dimension_runtime``.
Per docs/architecture/agent-graph.md the L2 subgraph is independent and must
not reference the L1 analysis node implementation.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import asdict
from datetime import datetime
from typing import Any, Dict, Optional

from langchain_core.messages import AIMessage

from app.config import get_dimension_config
from app.core.events import SSEEventType
from app.core.llm import create_llm
from app.core.settings import LLM_MODEL, MAX_TOKENS, LLM_STREAM_TIMEOUT
from app.utils.logger import get_logger
from app.agent.common.dimension_runtime import (
    generate_summary,
    load_dependency_reports,
    publish_dimension_complete,
    publish_dimension_delta,
    publish_dimension_start,
    run_rag,
    save_report_immediate,
    save_step_report,
)
from app.agent.explore.service import retrieve_evidence, render_evidence_prompt_section
from app.modules.prompts.concept import get_dimension_prompt as get_layer2_prompt
from app.modules.schema.contracts.evidence_contracts import ExplorationRequest

logger = get_logger(__name__)


# Cached LLM instance — reused across all L2 dimension analyses
_llm_cache: Optional[Any] = None


def _get_llm():
    global _llm_cache
    if _llm_cache is None:
        _llm_cache = create_llm(model=LLM_MODEL, temperature=0.7, max_tokens=MAX_TOKENS, streaming=True)
    return _llm_cache


def _build_revision_completed(state: Dict[str, Any], dim_key: str) -> Dict[int, list]:
    """根据 impact_tree 反查维度所属 wave，构建 revision_completed_dims 更新"""
    impact_tree = state.get("revision_impact_tree", {})
    result: Dict[int, list] = {}
    for wave, dims in impact_tree.items():
        if dim_key in dims:
            result[wave] = [dim_key]
    return result


async def analyze_l2_dimension(state: Dict[str, Any]) -> Dict[str, Any]:
    """L2-only dimension analysis worker.

    流程（与 L1 一致但仅 L2）：
    1. 获取配置
    2. RAG 查询（L2 rag_query 为空时通常为 no-op）
    3. 加载依赖报告（同层 + 跨层）
    4. EXPLORE 证据注入
    5. 组装 L2 Prompt（concept 模板）
    6. 流式 LLM + SSE
    7. 保存版本
    8. 返回状态更新
    """
    from ...services.sse import sse_manager
    from ...services.report_store import ReportStore

    dim_key = state.get("dimension_key")
    if not dim_key:
        return {"messages": [AIMessage(content="[执行失败] 缺少维度标识")]}

    is_revision = state.get("is_revision", False)
    session_id = state.get("session_id", "")
    phase = state.get("phase", "layer2")
    logger.info(f"[analyze_l2_dimension] {dim_key} (phase={phase})")

    # 1. 获取配置
    cfg = get_dimension_config(dim_key)
    if not cfg:
        return {"messages": [AIMessage(content=f"[执行失败] 配置缺失: {dim_key}")]}

    dim_name = getattr(cfg, "name", dim_key)
    dim_layer = 2
    config = state.get("config", {})

    # Send dimension_start early so frontend shows progress during RAG
    await publish_dimension_start(session_id, dim_key, dim_name, dim_layer, is_revision)
    logger.info(
        "[analyze_l2_dimension] START: dim=%s name=%s layer=%d revision=%s",
        dim_key, dim_name, dim_layer, is_revision,
    )

    # 2. RAG（L2 dims have empty rag_query -> usually a no-op returning ("", None)）
    rag_context, rag_log = await run_rag(dim_key, cfg, state)

    # 3. 从数据库加载依赖报告（按配置过滤）
    store = ReportStore.get_instance()
    deps, same_layer_contexts = await load_dependency_reports(
        dim_key, cfg, dim_layer, session_id, is_revision,
    )

    # 4. EXPLORE evidence service（L2 只注入证据，不调用 GIS/DataPipeline 工具）
    explore_section = ""
    try:
        explore_request = ExplorationRequest(
            run_id=f"{session_id}:{dim_key}:L{dim_layer}",
            request_type="spatial_lookup",
            query=dim_name,
            stage=f"L{dim_layer}",
            dimension_key=dim_key,
            query_purpose="context_injection",
            entity_scope=["parcels", "facilities", "roads", "annotations"],
        )
        explore_result = await retrieve_evidence(
            explore_request,
            session_id=session_id,
            village_name=config.get("village_name", ""),
        )
        explore_section = render_evidence_prompt_section(
            explore_result.evidence_bundle,
            explore_result.spatial_cognition,
        )
        if explore_section:
            logger.info(
                "[analyze_l2_dimension] %s: EXPLORE evidence injected (%d chars, %d facts)",
                dim_key, len(explore_section), len(explore_result.evidence_bundle.facts),
            )
    except Exception as e:
        logger.warning("[analyze_l2_dimension] %s: EXPLORE evidence failed: %s", dim_key, e)

    # 5. 组装 L2 Prompt（concept 模板）
    prompt = _build_prompt(
        cfg, state, rag_context, deps, same_layer_contexts, explore_section,
    )
    logger.info(f"[analyze_l2_dimension] {dim_key}: Prompt length = {len(prompt)} chars")

    # 5.5 统计收集 - 开始维度
    from ...utils.stats_collector import StatsCollector
    stats = StatsCollector.get_instance()
    stats.start_dimension(session_id, dim_key, dim_name, dim_layer)
    stats.record_prompt(session_id, dim_key, len(prompt))
    if rag_log:
        stats.record_rag_time(session_id, dim_key, rag_log.retrieval_latency_ms, rag_log.total_results)

    # 6. 流式 LLM + SSE
    llm = _get_llm()
    llm_start_time = time.time()

    llm_response = ""
    _last_publish_time = 0.0
    _PUBLISH_INTERVAL = 0.1  # 100ms throttle

    try:
        async with asyncio.timeout(LLM_STREAM_TIMEOUT):
            async for chunk in llm.astream(prompt):
                if hasattr(chunk, 'content') and chunk.content:
                    llm_response += chunk.content
                    now = time.time()
                    if now - _last_publish_time >= _PUBLISH_INTERVAL:
                        await publish_dimension_delta(
                            session_id, dim_key, dim_name, dim_layer, is_revision,
                            chunk.content, llm_response,
                        )
                        _last_publish_time = now
    except asyncio.TimeoutError:
        logger.error(f"[analyze_l2_dimension] {dim_key}: LLM stream timeout after {LLM_STREAM_TIMEOUT}s")
        await sse_manager.publish(session_id, {
            "type": SSEEventType.DIMENSION_ERROR,
            "dimension_key": dim_key,
            "dimension_name": dim_name,
            "layer": dim_layer,
            "error": f"LLM stream timeout ({LLM_STREAM_TIMEOUT}s)",
        })
        return {"messages": [AIMessage(content=f"[执行失败] LLM流式超时({LLM_STREAM_TIMEOUT}s)")]}
    except Exception as e:
        logger.error(f"[analyze_l2_dimension] {dim_key}: LLM 失败: {e}")
        await sse_manager.publish(session_id, {
            "type": SSEEventType.DIMENSION_ERROR,
            "dimension_key": dim_key,
            "dimension_name": dim_name,
            "layer": dim_layer,
            "error": str(e),
        })
        return {"messages": [AIMessage(content=f"[执行失败] LLM错误: {e}")]}

    # Flush remaining delta (throttle may have skipped the last chunk)
    if llm_response and _last_publish_time > 0:
        await publish_dimension_delta(
            session_id, dim_key, dim_name, dim_layer, is_revision,
            "", llm_response,
        )

    llm_elapsed = time.time() - llm_start_time
    logger.info(f"[analyze_l2_dimension] {dim_key}: LLM completed in {llm_elapsed:.1f}s, output = {len(llm_response)} chars")

    # 6.5 统计收集 - 记录 LLM 时间和输出
    stats.record_llm_time(session_id, dim_key, llm_elapsed, len(llm_response))
    stats.end_dimension(session_id, dim_key)

    # 7. 准备报告数据（累积到 pending_reports，由 completion.py 批量写入）
    store = ReportStore.get_instance()
    latest_version = await store.get_latest_version(session_id, dim_key)
    next_version = latest_version + 1
    revision_reason = state.get("revision_feedback") or state.get("feedback")

    # Generate report_id for pending_reports
    report_id = str(uuid.uuid4())

    # 7.5 生成结构化摘要
    structured_summary_str = await generate_summary(dim_key, dim_layer, llm_response)

    # 8. 准备 pending report 数据
    phase_key = f"layer{dim_layer}"
    pending_report = {
        "session_id": session_id,
        "dimension_key": dim_key,
        "layer": dim_layer,
        "version": next_version,
        "report_id": report_id,
        "content": llm_response,
        "summary": structured_summary_str,
        "revision_trigger": revision_reason,
        "knowledge_sources": asdict(rag_log) if rag_log and rag_log.rag_enabled else None,
        "generated_at": datetime.now(),
    }

    # 9. 发送完成事件
    await publish_dimension_complete(
        session_id, dim_key, dim_name, len(llm_response),
        structured_summary_str, report_id, next_version, dim_layer, is_revision,
    )
    logger.info(
        "[analyze_l2_dimension] COMPLETE: dim=%s layer=%d words=%d version=%d revision=%s",
        dim_key, dim_layer, len(llm_response), next_version, is_revision,
    )

    # 10. State update - accumulate into pending_reports, reducer handles merge
    result = {
        "messages": [AIMessage(content=llm_response, metadata={"dimension_key": dim_key})],
        "completed_dimensions": {phase_key: [dim_key]},
        "pending_reports": [pending_report],
        "layer_char_counts": {dim_layer: len(llm_response)},
    }

    # 立即写入 DB，使并行节点可通过 DB 回退路径获取依赖报告
    await save_report_immediate(store, pending_report)

    # L2 维度步骤 Report（供 positioning-trace 面板定位）
    try:
        from app.services.report_store import split_instruction

        _, instr = split_instruction(llm_response)
        await save_step_report(
            session_id, "L2",
            step_name=f"analyze_l2_dimension:{dim_key}",
            dimension_key=dim_key,
            layer=dim_layer,
            is_revision=is_revision,
            outputs={
                "report_id": report_id,
                "word_count": len(llm_response),
                "instruction_len": len(instr),
                "has_instruction": bool(instr),
            },
            diagnostics={
                "rag_sources": len(rag_log.sources) if rag_log and rag_log.rag_enabled else 0,
                "kg_cognition": bool(explore_section),
            },
        )
    except Exception as e:
        logger.debug(f"[analyze_l2_dimension] {dim_key}: step report failed: {e}")

    # 级联修订：记录本维度完成的波次
    if is_revision:
        rev_completed = _build_revision_completed(state, dim_key)
        if rev_completed:
            result["revision_completed_dims"] = rev_completed
            result["is_revision"] = True
        # 返回 revision_impact_tree 以确保 fan-in reducer 能保留该值
        impact_tree = state.get("revision_impact_tree")
        if impact_tree:
            result["revision_impact_tree"] = impact_tree

    return result


def _build_prompt(
    cfg: Any,
    state: Dict[str, Any],
    rag_context: str = "",
    deps: str = "",
    same_layer_contexts: str = "",
    explore_section: str = "",
) -> str:
    """组装 L2 Prompt - 使用 concept 模板"""
    dim_key = getattr(cfg, 'key', state.get("dimension_key", ""))
    dim_name = getattr(cfg, 'name', dim_key)

    project_name = state.get("project_name", "村庄")
    village_name = state.get("config", {}).get("village_name", project_name)
    task_desc = state.get("config", {}).get("task_description", "制定村庄发展规划")
    constraints = state.get("config", {}).get("constraints", "无特殊约束")

    # 级联修订指令
    revision_instruction = ""
    if state.get("is_revision"):
        revision_feedback = state.get("revision_feedback", "")
        revision_instruction = f"""【级联修订指令 - 必须执行】
你的上级专家对你的报告提出了以下驳回意见：

"{revision_feedback}"

你需要根据驳回意见对报告内容进行实质性修改：
1. 仔细理解驳回意见中提出的问题和要求
2. 在报告正文中体现驳回意见要求的调整方向
3. 修改后的报告应能体现出与修改前的明确差异
4. 保留原有报告格式和结构框架
5. 不要添加"修订摘要"章节，直接在正文中修改相关内容"""

    return get_layer2_prompt(
        dimension_key=dim_key,
        analysis_report=deps,
        task_description=task_desc,
        constraints=constraints,
        knowledge_context=rag_context or "",
        revision_instruction=revision_instruction,
        layer2_contexts=same_layer_contexts,  # 传递同层依赖报告
        professional_data=explore_section,  # EXPLORE 证据作为专业数据
    )


__all__ = ["analyze_l2_dimension", "_get_llm"]
