"""
维度分析节点 - 简化版

直接执行维度分析，无需中间 executor 层。
"""

import asyncio
import time
import uuid
import json
from dataclasses import asdict
from datetime import datetime
from enum import Enum
from typing import Dict, Any, List
from langchain_core.messages import AIMessage
from app.config import get_dimension_config, get_dimension_layer, list_dimensions
from app.core.settings import (
    BACKGROUND_SUMMARY_ENRICHMENT,
    L1_LLM_MAX_CONCURRENT,
    L1_LLM_TIMEOUT_S,
    L1_MAX_TOKENS,
    L1_TRANSIENT_RETRIES,
    L1_TRANSIENT_RETRY_BACKOFF_S,
)
from app.contracts.events import SSEEventType
from app.infrastructure.logging import get_logger
from app.infrastructure.llm.dimension_runtime import (
    enrich_summary_background,
    generate_summary,
    generate_summary_regex,
    load_dependency_reports,
    publish_dimension_complete,
    publish_dimension_delta,
    publish_dimension_start,
    provider_failure_open,
    trip_provider_failure,
    dimension_failure_attempt,
    run_rag,
    save_report_immediate,
    save_step_report,
)
from app.infrastructure.tasks.task_supervisor import build_summary_task_key

logger = get_logger(__name__)


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


def _build_revision_completed(state: Dict[str, Any], dim_key: str) -> Dict[int, List[str]]:
    """根据 impact_tree 反查维度所属 wave，构建 revision_completed_dims 更新"""
    impact_tree = state.get("revision_impact_tree", {})
    result: Dict[int, List[str]] = {}
    for wave, dims in impact_tree.items():
        if dim_key in dims:
            result[wave] = [dim_key]
    return result


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
    from app.infrastructure.events import event_hub as sse_manager

    # Debug: log revision_impact_tree at entry
    if state.get("is_revision"):
        logger.info(
            "[analyze_dimension] Revision entry: dim=%s, impact_tree=%s",
            state.get("dimension_key"),
            state.get("revision_impact_tree"),
        )
    from app.infrastructure.reports.report_store import ReportStore

    dim_key = state.get("dimension_key")
    if not dim_key:
        return {"messages": [AIMessage(content="[执行失败] 缺少维度标识")]}

    is_revision = state.get("is_revision", False)

    session_id = state.get("session_id", "")
    phase = state.get("phase", "layer1")
    logger.info(f"[analyze_dimension] {dim_key} (phase={phase})")

    # 1. 获取配置
    cfg = get_dimension_config(dim_key)
    if not cfg:
        return {"messages": [AIMessage(content=f"[执行失败] 配置缺失: {dim_key}")]}

    dim_name = getattr(cfg, 'name', dim_key)
    prefer_doc_types = getattr(cfg, "prefer_doc_types", None) or None
    dim_layer = getattr(cfg, 'layer', get_dimension_layer(dim_key) or 3)

    # 2+3. GIS 和 RAG 并行执行（两者访问独立数据源，无逻辑依赖）
    config = state.get("config", {})

    # Send dimension_start early so frontend shows progress during RAG
    await publish_dimension_start(session_id, dim_key, dim_name, dim_layer, is_revision)
    logger.info(
        "[analyze_dimension] START: dim=%s name=%s layer=%d revision=%s",
        dim_key, dim_name, dim_layer, is_revision,
    )


    from app.core.settings import RAG_TIMEOUT_S

    try:
        async with asyncio.timeout(RAG_TIMEOUT_S):
            rag_context, rag_log = await run_rag(dim_key, cfg, state)
    except asyncio.TimeoutError:
        logger.warning(
            "[analyze_dimension] %s: RAG retrieval timed out after %ss", dim_key, RAG_TIMEOUT_S,
        )
        rag_context, rag_log = "", None

    # 4. 从数据库加载依赖报告（按配置过滤）
    store = ReportStore.get_instance()
    deps, same_layer_contexts = await load_dependency_reports(
        dim_key, cfg, dim_layer, session_id, is_revision,
    )

    # 5. DataPipeline: execute tools and format professional data
    professional_data_section = ""
    try:
        from app.domain.assessment.pipeline import DataPipeline
        from app.domain.assessment.formatters import generate_professional_data_section
        pipeline = DataPipeline()

        # Only load dependency data if dimension has tools configured
        tool_names = getattr(cfg, "tools", []) or []
        structured_summary = None

        if tool_names:
            try:
                # Canonical upstream facts come from the typed L1Snapshot
                # artifact, not from re-reading report summaries as input.
                from app.infrastructure.artifacts.runtime import load_artifact
                from app.contracts.domain.l1_contracts import L1Snapshot

                dep_keys = getattr(cfg, "layer_depends_on", []) or []
                snapshot = load_artifact(state, "l1_snapshot", L1Snapshot)
                by_dimension = getattr(snapshot, "facts_by_dimension", None) or {}
                merged_metrics = {}
                for dk in dict.fromkeys(dep_keys):
                    facts = by_dimension.get(dk) or []
                    if facts:
                        merged_metrics[f"{dk}_facts"] = facts
                if merged_metrics:
                    state["_dep_metrics"] = merged_metrics
                    logger.info(
                        "[analyze_dimension] %s: loaded %d dep fact groups for tools %s from l1_snapshot",
                        dim_key, len(merged_metrics), tool_names,
                    )
            except Exception as e:
                logger.warning(f"[analyze_dimension] {dim_key}: failed to load l1_snapshot facts: {e}")

        professional_data = await pipeline.get_professional_data(dim_key, structured_summary, state)
        professional_data_section = generate_professional_data_section(dim_key, professional_data)
        if professional_data_section:
            logger.info(f"[analyze_dimension] {dim_key}: professional data injected ({len(professional_data_section)} chars)")
    except Exception as e:
        logger.warning(f"[analyze_dimension] {dim_key}: DataPipeline failed: {e}")

    # run_rag is the unified EvidenceBundle adapter; no second retrieval call.
    explore_section = ""
    explore_audit = {
        "fact_statements": [],
        "fact_count": 0,
        "source_refs": [f"evidence_adapter:{session_id}:{dim_key}"],
        "kg_confidence": 0.0,
        "kg_topology_facts": [],
    }

    # 6. 组装 Prompt
    prompt = _build_prompt(
        cfg, state, rag_context, deps, same_layer_contexts,
        professional_data_section=professional_data_section,
        explore_section=explore_section,
        quality_feedback=state.get("quality_feedback", ""),
    )
    logger.info(f"[analyze_dimension] {dim_key}: Prompt length = {len(prompt)} chars")

    # 6.5 统计收集 - 开始维度
    from app.infrastructure.llm.stats_collector import StatsCollector
    stats = StatsCollector.get_instance()
    stats.start_dimension(session_id, dim_key, dim_name, dim_layer)
    stats.record_prompt(session_id, dim_key, len(prompt))
    if rag_log:
        stats.record_rag_time(session_id, dim_key, rag_log.retrieval_latency_ms, rag_log.total_results)

    # 7. L1 dual-response: report body + structured observations (function calling)
    if provider_failure_open(session_id):
        return {
            "dimension_retry_counts": dimension_failure_attempt(state, dim_key),
            "provider_failures": [{
                "stage": f"L{dim_layer}", "dimension": dim_key,
                "code": "llm_provider_circuit_open",
                "message": "LLM provider circuit is open after a prior session failure",
            }],
        }
    llm_start_time = time.time()

    report_body = ""
    observations: List[Any] = []
    try:
        from app.domain.assessment.observation_draft import L1DimensionOutput
        from app.infrastructure.llm.structured import run_structured_output

        # Instructor owns the L1 dual-response contract (report_body +
        # observations). Bounded schema reasks keep malformed results out of
        # downstream state.
        _L1_SYSTEM = (
            f"【dimension_key={dim_key}】你是村庄规划 L1 现状观察节点。同时输出两部分："
            "report_body 写 800-1600 字的维度现状分析正文（用【主题】标记段落、以【事实】开头的可核验事实行、"
            "markdown 表格列清单）；observations 写正文明确出现的现状空间对象"
            "（entity_type 只能是 现状设施/现状项目/现状分区/自然村/道路/水系/地物），"
            "最多 12 个对象，每个对象含 entity_type/name/location/relation/description/scale。"
            "location 优先自然村名，道路给走向、水系给流向；relation 写空间关系。"
            "正文中的聚合空间对象也必须记录：例如“现状道路131条/道路网络”至少输出1条entity_type=道路的观察，"
            "公共服务集中于某村、地质灾害点、自然村、水系和现状设施同理；name可以是正文中的聚合对象名，"
            "location或relation必须复用正文中的空间锚点。只有正文确实没有任何空间对象时才返回空数组。"
            "只摘录正文已出现的内容，不得编造；不要把规划建议写进L1观察。"
            "传输格式必须是一个且仅一个 JSON object："
            "{\"report_body\":\"...\",\"observations\":[{\"entity_type\":\"...\",\"name\":\"...\",\"location\":\"...\",\"relation\":\"...\",\"description\":\"...\",\"scale\":\"...\"}]}。"
            "禁止在 JSON object 外输出 Markdown、解释文字或代码 fence；report_body 字段内部可以包含 Markdown。"
        )
        # Fail FAST on a bounded Instructor request: a timeout or provider
        # failure trips the existing circuit path instead of stalling the whole
        # L1 layer for unbounded retries.
        output = await run_structured_output(
            L1DimensionOutput,
            [
                {"role": "system", "content": _L1_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            max_retries=1,
            timeout=L1_LLM_TIMEOUT_S,
            temperature=0.3,
            max_tokens=L1_MAX_TOKENS,
            incomplete_output_max_tokens=L1_MAX_TOKENS,
            max_concurrent=L1_LLM_MAX_CONCURRENT,
            semaphore_scope="l1",
            transient_retries=L1_TRANSIENT_RETRIES,
            transient_retry_backoff_s=L1_TRANSIENT_RETRY_BACKOFF_S,
        )
        if output is None:
            raise ValueError("L1 provider returned unparseable dual response")
        report_body = (output.report_body or "").strip()
        observations = list(output.observations or [])
    except asyncio.TimeoutError:
        trip_provider_failure(session_id)
        logger.error(f"[analyze_dimension] {dim_key}: L1 LLM timeout after {L1_LLM_TIMEOUT_S}s")
        await sse_manager.publish(session_id, {
            "type": SSEEventType.DIMENSION_ERROR,
            "dimension_key": dim_key,
            "dimension_name": dim_name,
            "layer": dim_layer,
            "error": f"L1 LLM timeout ({L1_LLM_TIMEOUT_S}s)",
        })
        return {
            "messages": [AIMessage(content=f"[执行失败] L1 LLM超时({L1_LLM_TIMEOUT_S}s)")],
            "dimension_retry_counts": dimension_failure_attempt(state, dim_key),
            "provider_failures": [{
                "stage": f"L{dim_layer}",
                "dimension": dim_key,
                "code": "llm_stream_timeout",
                "message": f"L1 LLM timeout ({L1_LLM_TIMEOUT_S}s)",
            }],
        }
    except Exception as e:
        from app.infrastructure.llm.dimension_runtime import is_provider_failure

        if is_provider_failure(e):
            trip_provider_failure(session_id)
        error_message = str(e)
        logger.error(f"[analyze_dimension] {dim_key}: typed L1 output failed: {error_message}")
        await sse_manager.publish(session_id, {
            "type": SSEEventType.DIMENSION_ERROR,
            "dimension_key": dim_key,
            "dimension_name": dim_name,
            "layer": dim_layer,
            "error": error_message,
        })
        return {
            "messages": [AIMessage(content=f"[执行失败] LLM结构化输出错误: {error_message}")],
            "dimension_retry_counts": dimension_failure_attempt(state, dim_key),
            "provider_failures": [{
                "stage": f"L{dim_layer}",
                "dimension": dim_key,
                "code": "llm_typed_output_error",
                "message": error_message,
            }],
        }

    llm_response = report_body
    observations_json = json.dumps(
        [
            item.model_dump(mode="json") if hasattr(item, "model_dump") else item
            for item in observations
        ],
        ensure_ascii=False,
    )
    # 7.6 Observation quality validation (design: validation step after every
    # LLM call).  A dimension whose observations mostly lack a spatial anchor
    # is a quality defect: it must NOT be marked complete.  It is surfaced
    # through dimension_failures and retried with corrective feedback instead
    # of silently feeding incomplete facts downstream.
    from app.domain.assessment.observation_quality import validate_observations

    quality_report = validate_observations(
        [
            item.model_dump(mode="json") if hasattr(item, "model_dump") else item
            for item in observations
        ]
    )

    await publish_dimension_delta(
        session_id, dim_key, dim_name, dim_layer, is_revision,
        llm_response, llm_response,
    )
    llm_elapsed = time.time() - llm_start_time
    logger.info(f"[analyze_dimension] {dim_key}: LLM completed in {llm_elapsed:.1f}s, output = {len(llm_response)} chars")

    # 7.5 统计收集 - 记录 LLM 时间和输出
    stats.record_llm_time(session_id, dim_key, llm_elapsed, len(llm_response))
    stats.end_dimension(session_id, dim_key)

    # 8. 准备报告数据（累积到 pending_reports，由 completion.py 批量写入）
    store = ReportStore.get_instance()
    latest_version = await store.get_latest_version(session_id, dim_key)
    next_version = latest_version + 1
    revision_reason = state.get("revision_feedback") or state.get("feedback")

    # Generate report_id for pending_reports
    report_id = str(uuid.uuid4())

    # 8. Generate structured summary (before SSE event so it can reference it)
    structured_summary_str = generate_summary_regex(dim_key, dim_layer, llm_response)
    from app.bootstrap.composition import CompositionRoot

    if BACKGROUND_SUMMARY_ENRICHMENT:
        CompositionRoot.get_task_supervisor().create_task(
            build_summary_task_key(session_id, dim_layer, dim_key, next_version),
            enrich_summary_background(dim_key, dim_layer, llm_response, session_id, next_version),
        )

    # 9. Prepare pending report data for batch write
    phase_key = f"layer{dim_layer}"
    pending_report = {
        "session_id": session_id,
        "dimension_key": dim_key,
        "layer": dim_layer,
        "version": next_version,
        "report_id": report_id,
        "content": report_body,
        "instruction": observations_json,
        "summary": structured_summary_str,
        "revision_trigger": revision_reason,
        "knowledge_sources": asdict(rag_log) if rag_log and rag_log.rag_enabled else None,
        "generated_at": datetime.now(),
    }

    # 10. Send completion event (with structured_summary)
    try:
        structured_summary_obj = json.loads(structured_summary_str) if structured_summary_str else None
    except json.JSONDecodeError:
        structured_summary_obj = None

    await publish_dimension_complete(
        session_id, dim_key, dim_name, len(llm_response),
        structured_summary_str, report_id, next_version, dim_layer, is_revision,
    )
    logger.info(
        "[analyze_dimension] COMPLETE: dim=%s layer=%d words=%d version=%d revision=%s",
        dim_key, dim_layer, len(llm_response), next_version, is_revision,
    )

    # 11. State update - accumulate into pending_reports, reducer handles merge
    result = {
        "messages": [AIMessage(content=llm_response, metadata={"dimension_key": dim_key})],
        "pending_reports": [pending_report],
        "layer_char_counts": {dim_layer: len(llm_response)},
    }
    if quality_report.get("ok", True):
        result["completed_dimensions"] = {phase_key: [dim_key]}
    else:
        result["dimension_retry_counts"] = dimension_failure_attempt(state, dim_key)
        result["dimension_failures"] = [{
            "stage": f"L{dim_layer}",
            "dimension": dim_key,
            "code": "dimension_quality_failed",
            "message": quality_report.get("feedback", ""),
            "feedback": quality_report.get("feedback", ""),
        }]

    # 立即写入 DB，使并行节点可通过 DB 回退路径获取依赖报告
    await save_report_immediate(store, pending_report)

    # P2: L1/L2/L3 维度步骤 Report（供 positioning-trace 面板定位）
    if dim_layer in (1, 2, 3):
        try:
            await save_step_report(
                state.get("session_id", ""), f"L{dim_layer}",
                step_name=f"analyze_dimension:{dim_key}",
                dimension_key=dim_key,
                layer=dim_layer,
                inputs={
                    "dependency_reports_summary": _dependency_summary(deps),
                    "same_layer_dependency_reports_summary": _dependency_summary(same_layer_contexts),
                },
                outputs={
                    "report_id": report_id,
                    "word_count": len(llm_response),
                    "observation_count": len(observations),
                    "kg_evidence_consumed": explore_audit,
                },
                diagnostics={
                    "is_revision": state.get("is_revision", False),
                    "rag_sources": len(rag_log.sources) if rag_log and rag_log.rag_enabled else 0,
                    "kg_cognition": bool(explore_section),
                    "kg_fact_count": explore_audit["fact_count"],
                },
            )
        except Exception as e:
            logger.debug(f"[analyze_dimension] {dim_key}: step report failed: {e}")

    # 级联修订：记录本维度完成的波次
    if state.get("is_revision"):
        rev_completed = _build_revision_completed(state, dim_key)
        if rev_completed:
            result["revision_completed_dims"] = rev_completed

    return result


def _dependency_summary(text: str) -> Dict[str, Any]:
    """Compact dependency audit; full prose is only passed to the prompt."""
    import re

    return {
        "sections": re.findall(r"【([^】]+)】", text or ""),
        "chars": len(text or ""),
        "preview": (text or "")[:500],
    }


async def _generate_summary(dim_key: str, dim_layer: int, content: str, rag_log=None) -> str:
    """Generate structured JSON summary for a dimension report (delegates to shared runtime)."""
    return await generate_summary(dim_key, dim_layer, content)


def _build_prompt(cfg, state, rag_context, deps: str = "", same_layer_contexts: str = "", professional_data_section: str = "", explore_section: str = "", explore_brief_section: str = "", quality_feedback: str = "") -> str:
    """组装 Prompt - 使用 prompts 模块模板

    Args:
        cfg: 维度配置
        state: 当前状态
        rag_context: RAG 检索上下文
        deps: 前序依赖报告（从数据库加载）
        same_layer_contexts: 同层依赖报告
    """
    from app.infrastructure.llm.prompts.analysis import get_dimension_prompt as get_layer1_prompt
    from app.infrastructure.llm.prompts.concept import get_dimension_prompt as get_layer2_prompt
    from app.infrastructure.llm.prompts.detailed import get_dimension_prompt as get_layer3_prompt

    dim_key = getattr(cfg, 'key', state.get("dimension_key", ""))
    layer = getattr(cfg, 'layer', get_dimension_layer(dim_key) or 1)
    dim_name = getattr(cfg, 'name', DIMENSION_NAMES.get(dim_key, dim_key))

    project_name = state.get("project_name", "村庄")
    config = state.get("config", {})
    input_texts: Dict[str, str] = {}
    context_village_name = ""
    try:
        from app.infrastructure.context.planning_context_factory import get_cached_context

        context = get_cached_context(str(state.get("session_id", "")))
        if context is not None:
            input_texts = context.input_texts()
            context_village_name = str(getattr(context, "village_name", "") or "")
    except Exception:
        input_texts = {}
    village_name = context_village_name or config.get("village_name", project_name)
    village_data = input_texts.get("village_data", "")
    task_desc = input_texts.get("task_description", "制定村庄发展规划")
    constraints = input_texts.get("constraints", "无特殊约束")

    # Professional data from DataPipeline (tool results formatted for prompt)

    # 根据层级选择 Prompt 模板
    # 级联修订指令：独立参数，不再混入 knowledge_context
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

    # Quality-retry instruction: the previous run failed spatial-anchor
    # validation; re-prompt with the exact defect so the LLM repairs its
    # output instead of repeating it.
    if quality_feedback:
        quality_instruction = f'''质量修正指令 - 请严格执行。
上次输出未通过空间锚点校验，请重写并修正：

"{quality_feedback}"

要求：
1. 每条观测必须包含 name；
2. 每条观测尽量给出 location 或 relation 空间锚点；
3. 保持原有报告格式与结构，不要新增"修订摘要"章节。'''
        revision_instruction = (revision_instruction + "\n\n" + quality_instruction) if revision_instruction else quality_instruction

    if layer == 1:
        prompt = get_layer1_prompt(
            dimension_key=dim_key,
            raw_data=village_data + professional_data_section,
            village_name=village_name,
            task_description=task_desc,
            constraints=constraints,
            knowledge_context=rag_context or "",
            revision_instruction=revision_instruction,
            has_images=bool(state.get("image_ids")),
        )
        # EXPLORE 证据注入到 输出骨架 之前（不改 L1 模板）
        explore_section = explore_section or explore_brief_section
        if explore_section:
            prompt = prompt.replace(
                "**输出骨架**",
                f"\n\n{explore_section}\n\n**输出骨架**",
                1,
            )
        return prompt
    elif layer == 2:
        return get_layer2_prompt(
            dimension_key=dim_key,
            analysis_report=deps,
            task_description=task_desc,
            constraints=constraints,
            knowledge_context=rag_context or "",
            revision_instruction=revision_instruction,
            layer2_contexts=same_layer_contexts,  # 传递同层依赖报告
            professional_data=professional_data_section + explore_section,  # 注入工具计算结果 + EXPLORE 证据
        )
    elif layer == 3:
        return get_layer3_prompt(
            dimension_key=dim_key,
            project_name=project_name,
            analysis_report=deps,
            planning_concept=deps,
            constraints=constraints,
            knowledge_context=rag_context or "",
            revision_instruction=revision_instruction,
            professional_data_section=professional_data_section + explore_section,
            natural_villages="",
        )

    # 默认通用模板
    return f"""请对 "{project_name}" 进行 {dim_name} 分析。

## 基础数据
{village_data[:2000]}

## 规划任务
{task_desc}

{professional_data_section}

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
