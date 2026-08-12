"""L3 PLAN dimension worker - analyze_l3_dimension.

Independent L3-only dimension analysis worker (Wave E). Mirrors the shared
L1/L2 dimension flow but is restricted to the L3 detail-planning layer and
reuses the shared runtime helpers from ``app.infrastructure.llm.dimension_runtime``.
Per docs/architecture/agent-graph.md the L3 subgraph is independent and must
not reference the L1 analysis node implementation.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
import uuid
from dataclasses import asdict
from datetime import datetime
from typing import Any, Dict, List

from langchain_core.messages import AIMessage

from app.config import get_dimension_config
from app.core.events import SSEEventType
from app.core.settings import LLM_STREAM_TIMEOUT
from app.utils.logger import get_logger
from app.infrastructure.llm.dimension_runtime import (
    enrich_summary_background,
    generate_summary,
    generate_summary_regex,
    load_layered_dependency_reports,
    publish_dimension_complete,
    publish_dimension_delta,
    publish_dimension_start,
    provider_failure_open,
    trip_provider_failure,
    dimension_failure_attempt,
    run_rag,
    save_report_immediate,
    save_step_report,
    strip_model_reasoning,
)
from app.evidence.retrieval.evidence_service import retrieve_evidence, render_evidence_prompt_section
from app.modules.prompts.detailed import get_dimension_prompt as get_layer3_prompt
from app.modules.schema.contracts.evidence_contracts import ExplorationRequest
from app.contracts.program import PlanningClaimSet
from app.infrastructure.tasks.task_supervisor import build_summary_task_key

logger = get_logger(__name__)


# Cached LLM instance — reused across all L3 dimension analyses
def _build_revision_completed(state: Dict[str, Any], dim_key: str) -> Dict[int, list]:
    """根据 impact_tree 反查维度所属 wave，构建 revision_completed_dims 更新"""
    impact_tree = state.get("revision_impact_tree", {})
    result: Dict[int, list] = {}
    for wave, dims in impact_tree.items():
        if dim_key in dims:
            result[wave] = [dim_key]
    return result


_NATURAL_VILLAGE_RE = re.compile(r"[\u4e00-\u9fff]{2}")


def _extract_natural_villages(text: str) -> str:
    """从上游 L1 报告提取自然村名单（已知自然村闭集过滤 → 顿号拼接）。

    Location hints for L3 claims are restricted to known, resolvable villages;
    the source is the L1 socio-economic report and the data-layer gazetteer.
    """
    try:
        from app.modules.parsing.natural_villages import _KNOWN_NATURAL_VILLAGES
    except Exception:
        _KNOWN_NATURAL_VILLAGES = set()
    found: List[str] = []
    for m in _NATURAL_VILLAGE_RE.finditer(text or ""):
        name = m.group(0)
        if name in _KNOWN_NATURAL_VILLAGES and name not in found:
            found.append(name)
    return "、".join(found)


def _location_evidence(text: str) -> str:
    """Extract compact, source-backed location rows for the L3 prompt.

    The complete dependency reports remain in the prompt.  This separate
    block makes the spatial provenance decision explicit and prevents the
    model from turning a village list into an unsupported project location.
    """
    try:
        from app.modules.parsing.natural_villages import _KNOWN_NATURAL_VILLAGES
    except Exception:
        _KNOWN_NATURAL_VILLAGES = set()
    rows: List[str] = []
    seen: set[str] = set()
    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        if not line or not any(name in line for name in _KNOWN_NATURAL_VILLAGES):
            continue
        if not any(token in line for token in ("位于", "分布", "涉及", "集中", "位置", "布局")):
            continue
        if line in seen:
            continue
        seen.add(line)
        rows.append(line[:320])
        if len(rows) >= 60:
            break
    return "\n".join(f"- {row}" for row in rows) or "（依赖报告未提供可核验的对象—村庄位置关系）"


def _resolvable_villages(session_id: str) -> str:
    """Return only village aliases currently backed by real BSMs."""
    try:
        from app.services.context.planning_context import get_cached_context

        context = get_cached_context(session_id)
        names: List[str] = []
        for entry in (getattr(getattr(context, "gazetteer", None), "entries", []) or []):
            if not getattr(entry, "bsms", None):
                continue
            name = str(getattr(entry, "name", "") or "")
            if name.endswith(("村", "自然村")) and name not in names:
                names.append(name)
        return "、".join(names)
    except Exception:
        return ""


async def analyze_l3_dimension(state: Dict[str, Any]) -> Dict[str, Any]:
    """L3-only dimension analysis worker.

    流程（与 L1/L2 一致但仅 L3）：
    1. 获取配置
    2. RAG 查询
    3. 加载分层依赖报告（同层 + L1/L2 跨层分开）
    4. EXPLORE 证据注入
    5. 组装 L3 claims prompt（detailed 模板）
    6. Structured LLM output + SSE
    7. 保存版本
    8. 返回状态更新
    """
    from app.infrastructure.events import event_hub as sse_manager
    from ...services.report_store import ReportStore

    dim_key = state.get("dimension_key")
    if not dim_key:
        return {"messages": [AIMessage(content="[执行失败] 缺少维度标识")]}

    is_revision = state.get("is_revision", False)
    session_id = state.get("session_id", "")
    phase = state.get("phase", "layer3")
    logger.info(f"[analyze_l3_dimension] {dim_key} (phase={phase})")

    # 1. 获取配置
    cfg = get_dimension_config(dim_key)
    if not cfg:
        return {"messages": [AIMessage(content=f"[执行失败] 配置缺失: {dim_key}")]}

    dim_name = getattr(cfg, "name", dim_key)
    dim_layer = 3
    config = state.get("config", {})

    # Send dimension_start early so frontend shows progress during RAG
    await publish_dimension_start(session_id, dim_key, dim_name, dim_layer, is_revision)
    logger.info(
        "[analyze_l3_dimension] START: dim=%s name=%s layer=%d revision=%s",
        dim_key, dim_name, dim_layer, is_revision,
    )

    # 2. RAG
    rag_context, rag_log = await run_rag(dim_key, cfg, state)

    # 3. 从数据库加载分层依赖报告（同层 + L1/L2 跨层分开）
    store = ReportStore.get_instance()
    l1_deps, l2_deps, same_layer_contexts = await load_layered_dependency_reports(
        dim_key, cfg, dim_layer, session_id, is_revision,
    )

    # 4. EXPLORE evidence service（L3 只注入证据，不调用 GIS/DataPipeline 工具）
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
                "[analyze_l3_dimension] %s: EXPLORE evidence injected (%d chars, %d facts)",
                dim_key, len(explore_section), len(explore_result.evidence_bundle.facts),
            )
    except Exception as e:
        logger.warning("[analyze_l3_dimension] %s: EXPLORE evidence failed: %s", dim_key, e)

    # 5. 组装 L3 Prompt（detailed 模板）
    same_layer_prompt = same_layer_contexts
    if dim_key == "project_bank":
        from app.domain.program.claim_projection import compact_claim_context

        same_layer_prompt = compact_claim_context(same_layer_contexts)
        logger.info(
            "[analyze_l3_dimension] %s: compacted same-layer claims %d -> %d chars",
            dim_key,
            len(same_layer_contexts),
            len(same_layer_prompt),
        )
    prompt = _build_prompt(
        cfg, state, rag_context, l1_deps, l2_deps, same_layer_prompt, "", explore_section,
        resolvable_villages=_resolvable_villages(session_id),
    )
    logger.info(f"[analyze_l3_dimension] {dim_key}: Prompt length = {len(prompt)} chars")

    # 5.5 统计收集 - 开始维度
    from ...utils.stats_collector import StatsCollector
    stats = StatsCollector.get_instance()
    stats.start_dimension(session_id, dim_key, dim_name, dim_layer)
    stats.record_prompt(session_id, dim_key, len(prompt))
    if rag_log:
        stats.record_rag_time(session_id, dim_key, rag_log.retrieval_latency_ms, rag_log.total_results)

    # 6. 流式 LLM + SSE
    from app.domain.program.claim_draft import normalize_claim_draft_set
    from app.infrastructure.llm import get_planning_claim_generator

    claim_generator = get_planning_claim_generator()
    if provider_failure_open(session_id):
        return {
            "dimension_retry_counts": dimension_failure_attempt(state, dim_key),
            "fatal_error": {
                "stage": f"L{dim_layer}", "dimension": dim_key,
                "code": "llm_provider_circuit_open",
                "message": "LLM provider circuit is open after a prior session failure",
            }
        }
    llm_start_time = time.time()

    claim_set: PlanningClaimSet | None = None
    llm_response = ""

    try:
        async with asyncio.timeout(LLM_STREAM_TIMEOUT):
            draft_set = await claim_generator.generate(prompt)
            claim_set = normalize_claim_draft_set(draft_set, dimension_key=dim_key)
    except asyncio.TimeoutError:
        trip_provider_failure(session_id)
        logger.error(f"[analyze_l3_dimension] {dim_key}: LLM stream timeout after {LLM_STREAM_TIMEOUT}s")
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
                "stage": f"L{dim_layer}", "dimension": dim_key,
                "code": "llm_stream_timeout",
                "message": f"LLM stream timeout ({LLM_STREAM_TIMEOUT}s)",
            },
        }
    except Exception as e:
        trip_provider_failure(session_id)
        logger.error(f"[analyze_l3_dimension] {dim_key}: LLM 失败: {e}")
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
                "stage": f"L{dim_layer}", "dimension": dim_key,
                "code": "llm_provider_error", "message": str(e),
            },
        }

    if claim_set is None:
        raise RuntimeError(f"L3 claim generation returned no result for {dim_key}")
    claim_set.dimension_key = dim_key
    claim_set.claims = [
        claim.model_copy(update={"dimension_key": claim.dimension_key or dim_key})
        for claim in claim_set.claims
    ]
    llm_response = claim_set.model_dump_json(indent=2)
    await publish_dimension_delta(
        session_id,
        dim_key,
        dim_name,
        dim_layer,
        is_revision,
        llm_response,
        llm_response,
    )
    llm_elapsed = time.time() - llm_start_time
    logger.info(f"[analyze_l3_dimension] {dim_key}: LLM completed in {llm_elapsed:.1f}s, output = {len(llm_response)} chars")

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

    # Claims are already structured; do not spend a second LLM call to
    # summarize the same authoritative non-executable output.
    structured_summary_str = json.dumps(
        {
            "dimension_key": dim_key,
            "layer": dim_layer,
            "claim_count": len(claim_set.claims),
            "claims_with_evidence": sum(bool(claim.evidence_refs) for claim in claim_set.claims),
        },
        ensure_ascii=False,
    )

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
        "[analyze_l3_dimension] COMPLETE: dim=%s layer=%d words=%d version=%d revision=%s",
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

    # L3 维度步骤 Report（供 positioning-trace 面板定位）
    try:
        await save_step_report(
            session_id, "L3",
            step_name=f"analyze_l3_dimension:{dim_key}",
            dimension_key=dim_key,
            layer=dim_layer,
            is_revision=is_revision,
            inputs={
                # The complete dependency prose is still passed to the LLM
                # prompt.  The persisted operator audit deliberately keeps a
                # compact summary so reports remain readable.
                "dependency_reports_summary": _dependency_summary(l1_deps),
                "l2_dependency_reports_summary": _dependency_summary(l2_deps),
                "same_layer_dependency_reports_summary": _dependency_summary(same_layer_contexts),
                "claims_only": True,
            },
            outputs={
                "report_id": report_id,
                "word_count": len(llm_response),
                "claim_count": len(claim_set.claims),
                "claims_with_evidence": sum(bool(claim.evidence_refs) for claim in claim_set.claims),
            },
            diagnostics={
                "rag_sources": len(rag_log.sources) if rag_log and rag_log.rag_enabled else 0,
                "kg_cognition": bool(explore_section),
            },
        )
    except Exception as e:
        logger.debug(f"[analyze_l3_dimension] {dim_key}: step report failed: {e}")

    # 级联修订：记录本维度完成的波次
    if is_revision:
        rev_completed = _build_revision_completed(state, dim_key)
        if rev_completed:
            result["revision_completed_dims"] = rev_completed

    return result


def _dependency_summary(text: str) -> Dict[str, Any]:
    """Summarize dependency prose for the human audit, not for the prompt."""
    from app.infrastructure.reports.report_store import split_instruction

    display, _ = split_instruction(text or "")
    sections = re.findall(r"^#{1,6}\s+(.+)$", display, re.MULTILINE)
    return {
        "sections": sections[:20],
        "chars": len(display),
        "preview": display[:500],
    }


def _build_prompt(
    cfg: Any,
    state: Dict[str, Any],
    rag_context: str = "",
    l1_deps: str = "",
    l2_deps: str = "",
    same_layer_contexts: str = "",
    professional_data_section: str = "",
    explore_section: str = "",
    resolvable_villages: str = "",
) -> str:
    """组装 L3 Prompt - 使用 detailed 模板（L1 现状与 L2 规划思路分开注入）"""
    dim_key = getattr(cfg, 'key', state.get("dimension_key", ""))

    project_name = state.get("project_name", "村庄")
    constraints = "无特殊约束"
    try:
        from app.services.context.planning_context import get_cached_context

        context = get_cached_context(str(state.get("session_id", "")))
        if context is not None:
            constraints = context.input_text("constraints", constraints)
    except Exception:
        pass

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

    return get_layer3_prompt(
        dimension_key=dim_key,
        project_name=project_name,
        analysis_report=l1_deps,
        planning_concept=l2_deps,
        constraints=constraints,
        knowledge_context=rag_context or "",
        revision_instruction=revision_instruction,
        professional_data_section=professional_data_section + explore_section,
        natural_villages=resolvable_villages or _extract_natural_villages(l1_deps),
        location_evidence=_location_evidence(l1_deps + "\n" + l2_deps),
        dimension_plans=same_layer_contexts,
    )


__all__ = ["analyze_l3_dimension"]
