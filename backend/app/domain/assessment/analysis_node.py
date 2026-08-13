"""
维度分析节点 - 简化版

直接执行维度分析，无需中间 executor 层。
"""

import asyncio
import time
import uuid
import json
import re
from dataclasses import asdict
from datetime import datetime
from enum import Enum
from typing import Dict, Any, List, Optional
from langchain_core.messages import AIMessage
from app.config import get_dimension_config, get_dimension_layer, list_dimensions
from app.core.settings import MAX_TOKENS, LLM_STREAM_TIMEOUT, BACKGROUND_SUMMARY_ENRICHMENT
from app.contracts.events import SSEEventType
from app.infrastructure.logging import get_logger
from app.evidence.retrieval.evidence_service import retrieve_evidence, render_evidence_prompt_section
from app.contracts.evidence.evidence_contracts import ExplorationRequest
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


    rag_context, rag_log = await run_rag(dim_key, cfg, state)

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

    # 5.5 + 5.6: EXPLORE evidence service (replaces _optimize_semantics + _build_explore_brief)
    explore_section = ""
    explore_audit = {
        "fact_statements": [],
        "fact_count": 0,
        "source_refs": [],
        "kg_confidence": 0.0,
        "kg_topology_facts": [],
    }
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
            village_name=state.get("config", {}).get("village_name", ""),
        )
        explore_section = render_evidence_prompt_section(
            explore_result.evidence_bundle,
            explore_result.spatial_cognition,
        )
        explore_audit = {
            "fact_statements": [f.statement for f in explore_result.evidence_bundle.facts],
            "fact_count": len(explore_result.evidence_bundle.facts),
            "source_refs": [s.reference for s in explore_result.evidence_bundle.sources],
            "kg_confidence": explore_result.spatial_cognition.kg_confidence,
            "kg_topology_facts": list(explore_result.spatial_cognition.topology_facts),
        }
        if explore_section:
            logger.info(
                "[analyze_dimension] %s: EXPLORE evidence injected (%d chars, %d facts)",
                dim_key, len(explore_section), len(explore_result.evidence_bundle.facts),
            )
    except Exception as e:
        logger.warning("[analyze_dimension] %s: EXPLORE evidence failed: %s", dim_key, e)

    # 6. 组装 Prompt
    prompt = _build_prompt(
        cfg, state, rag_context, deps, same_layer_contexts,
        professional_data_section=professional_data_section,
        explore_section=explore_section,
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
            "fatal_error": {
                "stage": f"L{dim_layer}", "dimension": dim_key,
                "code": "llm_provider_circuit_open",
                "message": "LLM provider circuit is open after a prior session failure",
            }
        }
    llm_start_time = time.time()

    report_body = ""
    observations: List[Any] = []
    try:
        from app.domain.assessment.observation_draft import L1DimensionOutput
        from app.infrastructure.llm.factory import create_llm as _create_llm

        structured = _create_llm(
            temperature=0.3, max_tokens=MAX_TOKENS, streaming=False
        ).with_structured_output(L1DimensionOutput, method="function_calling")
        async with asyncio.timeout(LLM_STREAM_TIMEOUT):
            output = await structured.ainvoke([
                {
                    "role": "system",
                    "content": (
                        "你是村庄规划 L1 现状观察节点。同时输出两部分："
                        "report_body 写维度现状分析正文（用【主题】标记段落、以【事实】开头的可核验事实行、"
                        "markdown 表格列清单）；observations 写正文明确出现的现状空间对象"
                        "（entity_type 只能是 现状设施/现状项目/现状分区/道路/水系/地物），"
                        "每个对象含 entity_type/name/location/description/scale。"
                        "只摘录正文已出现的内容，不得编造；无对象则返回空数组。"
                    ),
                },
                {"role": "user", "content": prompt},
            ])
        if output is None:
            raise ValueError("L1 provider returned None")
        if isinstance(output, str):
            output = L1DimensionOutput.model_validate_json(output)
        elif not isinstance(output, L1DimensionOutput):
            output = L1DimensionOutput.model_validate(output)
        report_body = (output.report_body or "").strip()
        observations = list(output.observations or [])
    except asyncio.TimeoutError:
        trip_provider_failure(session_id)
        logger.error(f"[analyze_dimension] {dim_key}: LLM stream timeout after {LLM_STREAM_TIMEOUT}s")
        await sse_manager.publish(session_id, {
            "type": SSEEventType.DIMENSION_ERROR,
            "dimension_key": dim_key,
            "dimension_name": dim_name,
            "layer": dim_layer,
            "error": f"LLM stream timeout ({LLM_STREAM_TIMEOUT}s)",
        })
        return {
            "messages": [AIMessage(content=f"[执行失败] LLM流式超时({LLM_STREAM_TIMEOUT}s)")],
            "dimension_retry_counts": dimension_failure_attempt(state, dim_key),
            "fatal_error": {
                "stage": f"L{dim_layer}",
                "dimension": dim_key,
                "code": "llm_stream_timeout",
                "message": f"LLM stream timeout ({LLM_STREAM_TIMEOUT}s)",
            },
        }
    except Exception as e:
        trip_provider_failure(session_id)
        logger.error(f"[analyze_dimension] {dim_key}: LLM 失败: {e}")
        await sse_manager.publish(session_id, {
            "type": SSEEventType.DIMENSION_ERROR,
            "dimension_key": dim_key,
            "dimension_name": dim_name,
            "layer": dim_layer,
            "error": str(e),
        })
        return {
            "messages": [AIMessage(content=f"[执行失败] LLM错误: {e}")],
            "dimension_retry_counts": dimension_failure_attempt(state, dim_key),
            "fatal_error": {
                "stage": f"L{dim_layer}",
                "dimension": dim_key,
                "code": "llm_provider_error",
                "message": str(e),
            },
        }

    llm_response = report_body
    observations_json = json.dumps(
        [
            item.model_dump(mode="json") if hasattr(item, "model_dump") else item
            for item in observations
        ],
        ensure_ascii=False,
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
        "completed_dimensions": {phase_key: [dim_key]},
        "pending_reports": [pending_report],
        "layer_char_counts": {dim_layer: len(llm_response)},
    }

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


_NATURAL_VILLAGE_RE = re.compile(r"[\u4e00-\u9fff]{2}")


def _extract_natural_villages(text: str) -> str:
    """从 L1 报告提取自然村名单（已知 12 村闭集过滤 → 顿号拼接）。

    Location extraction for report evidence uses known natural-village names,
    数据源 = L1 socio_economic 报告（"完整名单：田坑、黄竹、园寨…"）。
    """
    try:
        from app.data.ingestion.natural_villages import _KNOWN_NATURAL_VILLAGES
    except Exception:
        _KNOWN_NATURAL_VILLAGES = set()
    found: List[str] = []
    for m in _NATURAL_VILLAGE_RE.finditer(text or ""):
        name = m.group(0)
        if name in _KNOWN_NATURAL_VILLAGES and name not in found:
            found.append(name)
    return "、".join(found)


def _build_prompt(cfg, state, rag_context, deps: str = "", same_layer_contexts: str = "", professional_data_section: str = "", explore_section: str = "", explore_brief_section: str = "") -> str:
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
        # P8: L1 自然村名单注入 INSTRUCTION 位置列引导（已知 12 村枚举）
        return get_layer3_prompt(
            dimension_key=dim_key,
            project_name=project_name,
            analysis_report=deps,
            planning_concept=deps,
            constraints=constraints,
            knowledge_context=rag_context or "",
            revision_instruction=revision_instruction,
            professional_data_section=professional_data_section + explore_section,
            natural_villages=_extract_natural_villages(deps),
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
