"""
维度分析节点 - 简化版

直接执行维度分析，无需中间 executor 层。
"""

import asyncio
import os
import threading
import time
import uuid
import json
import re
from dataclasses import asdict
from datetime import datetime
from enum import Enum
from typing import Dict, Any, List, Optional
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from app.config import get_dimension_config, get_dimension_layer, list_dimensions
from app.core.llm import create_llm
from app.core.settings import MAX_TOKENS, LLM_STREAM_TIMEOUT
from app.core.events import SSEEventType
from app.utils.logger import get_logger
from app.agent.explore.service import retrieve_evidence, render_evidence_prompt_section
from app.modules.schema.contracts.evidence_contracts import ExplorationRequest
from app.agent.common.dimension_runtime import (
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
from app.services.task_supervisor import build_summary_task_key

logger = get_logger(__name__)


# Cached LLM instance — reused across all dimension analyses
_llm_cache: Optional[Any] = None
_L1_LLM_SLOTS = threading.BoundedSemaphore(
    max(1, int(os.getenv("L1_LLM_MAX_CONCURRENT", "3")))
)


def _get_llm():
    global _llm_cache
    if _llm_cache is None:
        _llm_cache = create_llm(temperature=0.7, max_tokens=MAX_TOKENS, streaming=True)
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
    from ...services.sse import sse_manager

    # Debug: log revision_impact_tree at entry
    if state.get("is_revision"):
        logger.info(
            "[analyze_dimension] Revision entry: dim=%s, impact_tree=%s",
            state.get("dimension_key"),
            state.get("revision_impact_tree"),
        )
    from ...services.report_store import ReportStore

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
        from app.agent.l1_observe.pipeline import DataPipeline
        from app.agent.l1_observe.formatters import generate_professional_data_section
        pipeline = DataPipeline()

        # Only load dependency data if dimension has tools configured
        tool_names = getattr(cfg, "tools", []) or []
        structured_summary = None

        if tool_names and dim_layer >= 2:
            try:
                # Load data from layer_depends_on dimensions
                dep_keys = getattr(cfg, "layer_depends_on", []) or []
                if dep_keys:
                    layer_summaries = await store.get_layer_summaries(session_id, 1)
                    from ...modules.parsing.schemas import get_dimension_schema
                    merged_metrics = {}
                    for dk in dep_keys:
                        raw = layer_summaries.get(dk)
                        if raw:
                            schema_cls = get_dimension_schema(dk)
                            try:
                                parsed = schema_cls.model_validate(raw)
                                if structured_summary is None:
                                    structured_summary = parsed
                                if hasattr(parsed, "metrics") and parsed.metrics:
                                    merged_metrics.update(parsed.metrics)
                                for fname, finfo in schema_cls.model_fields.items():
                                    if fname in ("dimension_key", "layer", "word_count", "key_points", "text_summary", "metrics"):
                                        continue
                                    val = getattr(parsed, fname, None)
                                    if val is not None:
                                        merged_metrics[fname] = val
                            except Exception:
                                pass
                    state["_dep_metrics"] = merged_metrics
                    logger.info(f"[analyze_dimension] {dim_key}: loaded {len(merged_metrics)} metrics for tools {tool_names} from deps {dep_keys}")
            except Exception as e:
                logger.warning(f"[analyze_dimension] {dim_key}: failed to load prior summaries: {e}")

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
    from ...utils.stats_collector import StatsCollector
    stats = StatsCollector.get_instance()
    stats.start_dimension(session_id, dim_key, dim_name, dim_layer)
    stats.record_prompt(session_id, dim_key, len(prompt))
    if rag_log:
        stats.record_rag_time(session_id, dim_key, rag_log.retrieval_latency_ms, rag_log.total_results)

    # 7. 流式 LLM + SSE
    llm = _get_llm()
    if provider_failure_open(session_id):
        return {
            "fatal_error": {
                "stage": f"L{dim_layer}", "dimension": dim_key,
                "code": "llm_provider_circuit_open",
                "message": "LLM provider circuit is open after a prior session failure",
            }
        }
    llm_start_time = time.time()

    llm_response = ""
    _last_publish_time = 0.0
    _PUBLISH_INTERVAL = 0.1  # 100ms throttle
    llm_input = prompt
    if dim_layer == 1:
        llm_input = [
            SystemMessage(
                content=(
                    "你是村庄规划L1现状观察节点。输出必须遵守以下协议，协议优先于其他写作习惯："
                    "先写维度分析正文；正文结束后单独一行输出字面量【INSTRUCTION】；"
                    "下一行必须是表头 | 类型 | 名称 | 位置 | 现状描述 | 证据来源 |，再下一行是 |---|---|---|---|---|；"
                    "之后每个现状空间对象一行。即使没有对象，也必须输出marker、表头和分隔行。"
                    "禁止用代码围栏包裹该部分，禁止改写marker。表格只能摘录正文明确出现的现状对象，不得编造。"
                )
            ),
            HumanMessage(content=prompt),
        ]

    await asyncio.to_thread(_L1_LLM_SLOTS.acquire)
    try:
        try:
            async with asyncio.timeout(LLM_STREAM_TIMEOUT):
                async for chunk in llm.astream(llm_input):
                    if hasattr(chunk, 'content') and chunk.content:
                        llm_response += chunk.content
                        now = time.time()
                        if now - _last_publish_time >= _PUBLISH_INTERVAL:
                            await publish_dimension_delta(
                                session_id, dim_key, dim_name, dim_layer, is_revision,
                                chunk.content, llm_response,
                            )
                            _last_publish_time = now
        finally:
            _L1_LLM_SLOTS.release()
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

    # Flush remaining delta (throttle may have skipped the last chunk)
    if llm_response and _last_publish_time > 0:
        await publish_dimension_delta(
            session_id, dim_key, dim_name, dim_layer, is_revision,
            "", llm_response,
        )

    llm_elapsed = time.time() - llm_start_time
    logger.info(f"[analyze_dimension] {dim_key}: LLM completed in {llm_elapsed:.1f}s, output = {len(llm_response)} chars")

    # The private section is a required output protocol.  Do not issue a
    # second "repair" generation or synthesize rows here: if it is missing,
    # preserve the violation in the audit so the gate can fail closed.
    instruction_repaired = False
    instruction_repair_source = ""
    if dim_layer == 1 and "【INSTRUCTION】" not in llm_response:
        logger.error(
            "[analyze_dimension] %s: L1 output protocol violation: missing INSTRUCTION",
            dim_key,
        )

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
    from app.services.composition import CompositionRoot

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
        "content": llm_response,
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

    # P0-1: L1 数据流闭环注入（详见 docs/superpowers/specs/2026-07-02-gis-review-exploration.md）
    # L1 完成后注入 _landuse_metrics（现状用地指标）
    # L2 纯粹化（v4）：L2 只产大致规划定位，不再注入 intent_targets 面积意向；L3 自洽
    if structured_summary_obj:
        try:
            if dim_layer == 1:
                _lm = _extract_landuse_metrics(structured_summary_obj, dim_key)
                if _lm:
                    result["_landuse_metrics"] = _lm
                    logger.info(f"[analyze_dimension] {dim_key}: injected _landuse_metrics = {_lm}")
        except Exception as e:
            logger.warning(f"[analyze_dimension] {dim_key}: L1/L2 injection failed: {e}")

    # 立即写入 DB，使并行节点可通过 DB 回退路径获取依赖报告
    await save_report_immediate(store, pending_report)

    # P2: L1/L2/L3 维度步骤 Report（供 positioning-trace 面板定位）
    if dim_layer in (1, 2, 3):
        try:
            from app.services.report_store import split_instruction

            _, instr = split_instruction(llm_response)
            await save_step_report(
                state.get("session_id", ""), f"L{dim_layer}",
                step_name=f"analyze_dimension:{dim_key}",
                dimension_key=dim_key,
                layer=dim_layer,
                inputs={
                    "dependency_reports_summary": _dependency_summary(deps),
                    "same_layer_dependency_reports_summary": _dependency_summary(same_layer_contexts),
                    "instruction_removed": True,
                },
                outputs={
                    "report_id": report_id,
                    "word_count": len(llm_response),
                    "instruction_len": len(instr),
                    "has_instruction": bool(instr),
                    "instruction_repaired": instruction_repaired,
                    "instruction_repair_source": instruction_repair_source,
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
            result["is_revision"] = True
        # 返回 revision_impact_tree 以确保 fan-in reducer 能保留该值
        # _preserve_impact_tree(a, b): b 有值则用 b，否则保留 a
        # 所有并行节点从同一 Send payload 获取相同 final_tree，不会冲突
        impact_tree = state.get("revision_impact_tree")
        if impact_tree:
            result["revision_impact_tree"] = impact_tree

    return result


def _dependency_summary(text: str) -> Dict[str, Any]:
    """Compact dependency audit; full prose is only passed to the prompt."""
    import re

    return {
        "sections": re.findall(r"【([^】]+)】", text or ""),
        "chars": len(text or ""),
        "preview": (text or "")[:500],
    }


def _extract_landuse_metrics(summary_obj: Any, dim_key: str) -> Dict[str, float]:
    """P0-1: 从 L1 结构化摘要中提取现状用地指标。

    优先从 land_use 维度提取 current_farmland_ha / current_construction_ha / ecological_area_ha，
    fallback 到 superior_planning 的约束下限值，再 fallback 到 ecological 维度的 min_ecological_redline_ha。

    Returns: {"farmland_ha": float, "construction_ha": float, "ecological_ha": float}
    若全部为空则返回空 dict（调用方据此跳过注入）。
    """
    if not isinstance(summary_obj, dict):
        return {}

    def _safe_float(v: Any) -> Optional[float]:
        if v is None or v == "":
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    farmland = _safe_float(summary_obj.get("current_farmland_ha"))
    construction = _safe_float(summary_obj.get("current_construction_ha"))
    ecological = _safe_float(summary_obj.get("ecological_area_ha"))

    # Fallback 1: superior_planning 约束下限值
    if farmland is None:
        farmland = _safe_float(summary_obj.get("min_farmland_protection_ha"))
    if ecological is None:
        ecological = _safe_float(summary_obj.get("min_ecological_redline_ha"))

    # Fallback 2: ecological 维度字段
    if ecological is None:
        ecological = _safe_float(summary_obj.get("planned_ecological_area_ha"))

    result: Dict[str, float] = {}
    if farmland is not None:
        result["farmland_ha"] = farmland
    if construction is not None:
        result["construction_ha"] = construction
    if ecological is not None:
        result["ecological_ha"] = ecological

    return result


def _extract_intent_targets(summary_obj: Any, dim_key: str) -> Dict[str, float]:
    """P0-2: 从 L2 结构化摘要中提取规划目标面积，映射到三区中文名。

    优先字段：planned_farmland_ha / planned_construction_ha / planned_ecological_ha
    Fallback 1：farmland_protection_ha / construction_land_target_ha / planned_ecological_area_ha
    Fallback 2：L1 约束下限 min_farmland_protection_ha / min_ecological_redline_ha

    Returns: {"农田保护区": float, "村庄建设区": float, "生态保护区": float}
    全空则返回空 dict（调用方跳过注入）。
    """
    if not isinstance(summary_obj, dict):
        return {}

    def _safe_float(v: Any) -> Optional[float]:
        if v is None or v == "":
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    farmland = _safe_float(summary_obj.get("planned_farmland_ha"))
    construction = _safe_float(summary_obj.get("planned_construction_ha"))
    ecological = _safe_float(summary_obj.get("planned_ecological_ha"))

    # Fallback 1: L2 目标字段别名
    if farmland is None:
        farmland = _safe_float(summary_obj.get("farmland_protection_ha"))
    if construction is None:
        construction = _safe_float(summary_obj.get("construction_land_target_ha"))
    if ecological is None:
        ecological = _safe_float(summary_obj.get("planned_ecological_area_ha"))

    # Fallback 2: L1 约束下限值（保底）
    if farmland is None:
        farmland = _safe_float(summary_obj.get("min_farmland_protection_ha"))
    if ecological is None:
        ecological = _safe_float(summary_obj.get("min_ecological_redline_ha"))

    result: Dict[str, float] = {}
    if farmland is not None:
        result["农田保护区"] = farmland
    if construction is not None:
        result["村庄建设区"] = construction
    if ecological is not None:
        result["生态保护区"] = ecological

    return result


async def _generate_summary(dim_key: str, dim_layer: int, content: str, rag_log=None) -> str:
    """Generate structured JSON summary for a dimension report (delegates to shared runtime)."""
    return await generate_summary(dim_key, dim_layer, content)


_NATURAL_VILLAGE_RE = re.compile(r"[\u4e00-\u9fff]{2}")


def _extract_natural_villages(text: str) -> str:
    """从 L1 报告提取自然村名单（已知 12 村闭集过滤 → 顿号拼接）。

    P8: L3 prompt 的 INSTRUCTION 位置列引导需要已知自然村名枚举，
    数据源 = L1 socio_economic 报告（"完整名单：田坑、黄竹、园寨…"）。
    """
    try:
        from app.modules.kg.enrichment.report_entity_enrichment import _KNOWN_NATURAL_VILLAGES
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
    from ...modules.prompts.analysis import get_dimension_prompt as get_layer1_prompt
    from ...modules.prompts.concept import get_dimension_prompt as get_layer2_prompt
    from ...modules.prompts.detailed import get_dimension_prompt as get_layer3_prompt

    dim_key = getattr(cfg, 'key', state.get("dimension_key", ""))
    layer = getattr(cfg, 'layer', get_dimension_layer(dim_key) or 1)
    dim_name = getattr(cfg, 'name', DIMENSION_NAMES.get(dim_key, dim_key))

    project_name = state.get("project_name", "村庄")
    village_name = state.get("config", {}).get("village_name", project_name)
    village_data = state.get("config", {}).get("village_data", "")
    task_desc = state.get("config", {}).get("task_description", "制定村庄发展规划")
    constraints = state.get("config", {}).get("constraints", "无特殊约束")

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
        # P0-1/P0-2: inject L1 _landuse_metrics + L2 intent_targets for GIS_TOOL_GUIDE
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
            _landuse_metrics=state.get("_landuse_metrics", {}),
            intent_targets=state.get("intent_targets", {}),
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
