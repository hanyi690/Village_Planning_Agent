"""L2 STRATEGIZE dimension worker - analyze_l2_dimension.

Independent L2-only dimension analysis worker (Wave D). Mirrors the shared
L1 dimension flow but is restricted to the L2 planning-strategy layer and
reuses the shared runtime helpers from ``app.infrastructure.llm.dimension_runtime``.
Per docs/architecture/CURRENT_RUNTIME.md the L2 subgraph is independent and must
not reference the L1 analysis node implementation.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from dataclasses import asdict
from datetime import datetime
from typing import Any, Dict, Optional

from langchain_core.messages import AIMessage

from app.config import get_dimension_config
from app.contracts.events import SSEEventType
from app.core.settings import LLM_MAX_CONCURRENT, MAX_TOKENS, LLM_STREAM_TIMEOUT
from app.contracts.domain.l2_contracts import L2DecisionSet, L2ReportOutput
from app.domain.validation.l1_fact_catalog import (
    L1FactCatalog,
    build_l1_fact_catalog,
    empty_l1_fact_catalog,
    validate_l1_fact_catalog,
    validate_l1_fact_references,
)
from app.infrastructure.logging import get_logger
from app.infrastructure.llm.dimension_runtime import (
    load_dependency_reports,
    publish_dimension_complete,
    publish_dimension_delta,
    publish_dimension_start,
    provider_failure_open,
    trip_provider_failure,
    is_provider_failure,
    dimension_failure_attempt,
    run_rag,
    save_report_immediate,
    save_step_report,
    strip_model_reasoning,
)
from app.infrastructure.llm.prompts.concept import get_dimension_prompt as get_layer2_prompt

logger = get_logger(__name__)


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
    6. 结构化 LLM 决策集
    7. 保存版本
    8. 返回状态更新
    """
    from app.infrastructure.events import event_hub as sse_manager
    from app.infrastructure.reports.report_store import ReportStore

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

    # The run_rag adapter now retrieves and renders the unified EvidenceBundle;
    # this worker must not issue a second retrieve_evidence call.
    explore_section = ""
    explore_audit = {
        "fact_statements": [],
        "fact_count": 0,
        "source_refs": [f"evidence_adapter:{session_id}:{dim_key}"],
        "kg_confidence": 0.0,
        "kg_topology_facts": [],
    }

    # L1 is an explicit upstream fact producer.  Load its persisted snapshot
    # by ref so L2 consumes the same versioned facts that L3 will later use;
    # do not rely only on the dimension-report text search path.
    l1_fact_section, l1_fact_audit = _load_l1_fact_section(
        state,
        dimension_key=dim_key,
        source_dimensions=list(getattr(cfg, "layer_depends_on", []) or []),
    )
    if l1_fact_section:
        explore_section = f"{l1_fact_section}\n\n{explore_section}".strip()

    # 5. 组装 L2 Prompt（concept 模板）
    prompt = f"【dimension_key={dim_key}】\n" + _build_prompt(
        cfg, state, rag_context, deps, same_layer_contexts, explore_section,
    )
    logger.info(f"[analyze_l2_dimension] {dim_key}: Prompt length = {len(prompt)} chars")

    # 5.5 统计收集 - 开始维度
    from app.infrastructure.llm.stats_collector import StatsCollector
    stats = StatsCollector.get_instance()
    stats.start_dimension(session_id, dim_key, dim_name, dim_layer)
    stats.record_prompt(session_id, dim_key, len(prompt))
    if rag_log:
        stats.record_rag_time(session_id, dim_key, rag_log.retrieval_latency_ms, rag_log.total_results)

    # 6. Typed decision output.  The report body below is a deterministic
    # display projection of this object; it is never reparsed as semantics.
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
    from app.infrastructure.llm.structured import run_structured_output

    decision_system = (
        f"【L2 typed decision pass; dimension_key={dim_key}】\n"
        "你负责把给定的事实和规划背景转成 L2DecisionSet。只返回结构化 JSON，"
        "不要返回 Markdown、标题、表格或 report_body。只写有依据的目标、指标、策略、"
        "优先级、空间结构意图、冲突假设和证据缺口。空间结构只表达语义范围、关系和"
        "GROUND 所需前置条件，不生成坐标、WKT、GeoJSON、BSM 或最终选址。\n"
        "各对象的 ID 必须在本次输出内唯一，引用只能指向本次输出内已经存在的对象 ID；"
        "根对象只能包含 schema_version、dimension_key、objectives、metrics、strategies、"
        "priorities、spatial_structures、conflicts、evidence_gaps、source_refs、diagnostics；"
        "schema_version 固定为 2.0，所有数组都必须是 JSON 数组。PlanningObjective.kind 只能是"
        "goal/constraint/opportunity，PlanningObjective.status 只能是 observed/proposed/required；"
        "TargetMetric.direction 只能是 increase/decrease/maintain/range/unknown，"
        "TargetMetric.status 只能是 observed/proposed/required；StrategyRule.strength 只能是"
        "hard/soft/proposed；conflicts 和 evidence_gaps 的 severity 只能是 info/warning/error。\n"
        "没有证据时不要把对象标记为 observed；规划结论标记 proposed，无法支持的对象省略，"
        "并可用 evidence_gaps 记录缺口。规划建议指标必须标记 proposed，不能伪装为现状事实。"
        "数组字段始终返回 JSON 数组；没有内容时返回空数组。"
    ) + "\n\n" + _l2_fact_reference_rules(l1_fact_audit)
    async def _run_decision(validation_feedback: str = "") -> L2DecisionSet:
        system_content = decision_system
        max_retries = 2
        context_stage = "L2"
        if validation_feedback:
            system_content += (
                "\n\n【上一轮 L2 闭集校验反馈】\n"
                "只修正下列确定性校验问题；不得新增对象、改变语义或生成新的"
                "source_fact_refs。所有引用必须从上面的 allowed_l1_fact_ids JSON 数组逐字复制；"
                "无法引用时使用空数组并将对象标为 proposed、省略或写入 evidence_gaps。\n"
                + validation_feedback[:2000]
            )
            max_retries = 1
            context_stage = "L2_CLOSED_SET_RETRY"
        return await run_structured_output(
            L2DecisionSet,
            [
                {"role": "system", "content": system_content},
                {"role": "user", "content": prompt},
            ],
            max_retries=max_retries,
            timeout=LLM_STREAM_TIMEOUT,
            max_tokens=MAX_TOKENS,
            max_concurrent=max(1, int(os.getenv("L2_LLM_MAX_CONCURRENT", str(LLM_MAX_CONCURRENT)))),
            semaphore_scope="l2",
            temperature=0.3,
            context={"stage": context_stage, "dimension_key": dim_key, "session_id": session_id},
        )

    try:
        try:
            decision_set = await _run_decision()
        except Exception as first_error:
            from app.infrastructure.llm.structured import structured_failure_code

            failure_code = structured_failure_code(first_error)
            if is_provider_failure(first_error) or failure_code not in {
                "SCHEMA_INVALID",
                "TOOL_CALL_MISSING",
                "OUTPUT_TRUNCATED",
            }:
                raise
            decision_set = await _run_decision(
                "上一次结构化输出未通过响应 schema 校验（"
                f"{failure_code or 'SCHEMA_INVALID'}）。"
                "请严格返回 L2DecisionSet，并从 allowed_l1_fact_ids JSON 闭集逐字复制"
                " source_fact_refs；不要使用维度名、UUID、报告引用或 l1_fact: 前缀。"
            )
        decision_set = decision_set.model_copy(update={"dimension_key": dim_key})
        decision_set, semantic_error = (
            await _validate_l2_decision_with_one_closed_set_reask(
                decision_set,
                catalog=l1_fact_audit.get("fact_catalog") or empty_l1_fact_catalog(),
                catalog_digest=l1_fact_audit.get("catalog_digest", ""),
                run_decision=_run_decision,
            )
        )
    except asyncio.TimeoutError:
        trip_provider_failure(session_id)
        logger.error(f"[analyze_l2_dimension] {dim_key}: typed LLM timeout after {LLM_STREAM_TIMEOUT}s")
        await sse_manager.publish(session_id, {
            "type": SSEEventType.DIMENSION_ERROR,
            "dimension_key": dim_key,
            "dimension_name": dim_name,
            "layer": dim_layer,
            "error": f"L2 typed output timeout ({LLM_STREAM_TIMEOUT}s)",
        })
        return {
            "messages": [AIMessage(content=f"[执行失败] L2结构化输出超时({LLM_STREAM_TIMEOUT}s)")],
            "dimension_retry_counts": dimension_failure_attempt(state, dim_key),
            "provider_failures": [{
                "stage": f"L{dim_layer}", "dimension": dim_key,
                "code": "llm_typed_timeout",
                "message": f"L2 typed output timeout ({LLM_STREAM_TIMEOUT}s)",
            }],
        }
    except Exception as e:
        if is_provider_failure(e):
            trip_provider_failure(session_id)
        from app.infrastructure.llm.structured import structured_failure_code, structured_failure_summary

        error_message = structured_failure_summary(e)
        logger.error(f"[analyze_l2_dimension] {dim_key}: typed LLM failed: {error_message}")
        await sse_manager.publish(session_id, {
            "type": SSEEventType.DIMENSION_ERROR,
            "dimension_key": dim_key,
            "dimension_name": dim_name,
            "layer": dim_layer,
            "error": error_message,
        })
        return {
            "messages": [AIMessage(content=f"[执行失败] L2结构化输出错误: {error_message}")],
            "dimension_retry_counts": dimension_failure_attempt(state, dim_key),
            "provider_failures": [{
                "stage": f"L{dim_layer}", "dimension": dim_key,
                "code": structured_failure_code(e) or "llm_typed_output_error",
                "message": error_message,
            }],
        }

    if semantic_error:
        logger.error(
            "[analyze_l2_dimension] %s: typed decision semantic validation failed: %s",
            dim_key,
            semantic_error,
        )
        await sse_manager.publish(session_id, {
            "type": SSEEventType.DIMENSION_ERROR,
            "dimension_key": dim_key,
            "dimension_name": dim_name,
            "layer": dim_layer,
            "error": "L2 typed decision semantic validation failed",
        })
        return {
            "messages": [AIMessage(content="[执行失败] L2 结构化决策未通过语义闭合校验")],
            "dimension_retry_counts": dimension_failure_attempt(state, dim_key),
            "semantic_failures": [{
                "stage": f"L{dim_layer}",
                "dimension": dim_key,
                "code": "l2_semantic_validation_error",
                "message": semantic_error,
            }],
        }
    report_prompt = _build_l2_report_synthesis_prompt(dim_key, decision_set)
    try:
        report_output = await run_structured_output(
            L2ReportOutput,
            [
                {
                    "role": "system",
                    "content": (
                        "你正在执行 L2 report synthesis pass。只依据用户消息中的已验证"
                        "L2DecisionSet 生成 L2ReportOutput，不得重新生成或修改结构化决策。"
                    ),
                },
                {"role": "user", "content": report_prompt},
            ],
            max_retries=1,
            timeout=LLM_STREAM_TIMEOUT,
            max_tokens=max(
                256,
                int(os.getenv("L2_REPORT_MAX_TOKENS", str(min(MAX_TOKENS, 4096)))),
            ),
            max_concurrent=max(
                1,
                int(os.getenv("L2_LLM_MAX_CONCURRENT", str(LLM_MAX_CONCURRENT))),
            ),
            semaphore_scope="l2",
            temperature=0.3,
            context={
                "stage": "L2_REPORT",
                "dimension_key": dim_key,
                "session_id": session_id,
            },
        )
        llm_response = _require_l2_report_body(report_output.report_body)
    except asyncio.TimeoutError:
        trip_provider_failure(session_id)
        logger.error(
            "[analyze_l2_dimension] %s: report synthesis timeout after %ss",
            dim_key,
            LLM_STREAM_TIMEOUT,
        )
        await sse_manager.publish(session_id, {
            "type": SSEEventType.DIMENSION_ERROR,
            "dimension_key": dim_key,
            "dimension_name": dim_name,
            "layer": dim_layer,
            "error": f"L2 report synthesis timeout ({LLM_STREAM_TIMEOUT}s)",
        })
        return {
            "messages": [AIMessage(content=f"[执行失败] L2正文生成超时({LLM_STREAM_TIMEOUT}s)")],
            "dimension_retry_counts": dimension_failure_attempt(state, dim_key),
            "provider_failures": [{
                "stage": f"L{dim_layer}",
                "dimension": dim_key,
                "code": "llm_report_timeout",
                "message": f"L2 report synthesis timeout ({LLM_STREAM_TIMEOUT}s)",
            }],
        }
    except Exception as exc:
        if is_provider_failure(exc):
            trip_provider_failure(session_id)
        from app.infrastructure.llm.structured import structured_failure_code, structured_failure_summary

        error_message = structured_failure_summary(exc)
        logger.error(
            "[analyze_l2_dimension] %s: report synthesis failed: %s",
            dim_key,
            error_message,
        )
        await sse_manager.publish(session_id, {
            "type": SSEEventType.DIMENSION_ERROR,
            "dimension_key": dim_key,
            "dimension_name": dim_name,
            "layer": dim_layer,
            "error": error_message,
        })
        return {
            "messages": [AIMessage(content=f"[执行失败] L2正文结构化输出错误: {error_message}")],
            "dimension_retry_counts": dimension_failure_attempt(state, dim_key),
            "provider_failures": [{
                "stage": f"L{dim_layer}",
                "dimension": dim_key,
                "code": structured_failure_code(exc) or "llm_report_output_error",
                "message": error_message,
            }],
        }
    llm_elapsed = time.time() - llm_start_time
    logger.info(
        "[analyze_l2_dimension] %s: typed decision + report synthesis completed in %.1fs, output=%d chars",
        dim_key,
        llm_elapsed,
        len(llm_response),
    )

    await publish_dimension_delta(
        session_id,
        dim_key,
        dim_name,
        dim_layer,
        is_revision,
        llm_response,
        llm_response,
    )

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

    # The summary is a projection of the validated decision set, not a
    # regex/keyword interpretation of the report body.
    structured_summary_str = _decision_summary_json(decision_set, llm_response)

    # 8. 准备 pending report 数据
    phase_key = f"layer{dim_layer}"
    pending_report = {
        "session_id": session_id,
        "dimension_key": dim_key,
        "layer": dim_layer,
        "version": next_version,
        "report_id": report_id,
        "content": llm_response,
        "instruction": decision_set.model_dump_json(ensure_ascii=False),
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
        await save_step_report(
            session_id, "L2",
            step_name=f"analyze_l2_dimension:{dim_key}",
            dimension_key=dim_key,
            layer=dim_layer,
            inputs={
                "dependency_reports_summary": _dependency_summary(deps),
                "same_layer_dependency_reports_summary": _dependency_summary(same_layer_contexts),
                "typed_decision_set": True,
            },
            outputs={
                "report_id": report_id,
                "word_count": len(llm_response),
                "instruction_len": len(decision_set.model_dump_json()),
                "has_instruction": True,
                "decision_counts": {
                    "objectives": len(decision_set.objectives),
                    "metrics": len(decision_set.metrics),
                    "strategies": len(decision_set.strategies),
                    "priorities": len(decision_set.priorities),
                    "spatial_structures": len(decision_set.spatial_structures),
                    "conflicts": len(decision_set.conflicts),
                    "evidence_gaps": len(decision_set.evidence_gaps),
                },
                "kg_evidence_consumed": explore_audit,
            },
            diagnostics={
                "is_revision": is_revision,
                "rag_sources": len(rag_log.sources) if rag_log and rag_log.rag_enabled else 0,
                "kg_cognition": bool(explore_section),
                "kg_fact_count": explore_audit["fact_count"],
                "l1_fact_count": l1_fact_audit["fact_count"],
                "l1_fact_catalog_digest": l1_fact_audit["catalog_digest"],
                "l1_allowed_fact_count": len(l1_fact_audit["allowed_fact_ids"]),
            },
        )
    except Exception as e:
        logger.debug(f"[analyze_l2_dimension] {dim_key}: step report failed: {e}")

    # 级联修订：记录本维度完成的波次
    if is_revision:
        rev_completed = _build_revision_completed(state, dim_key)
        if rev_completed:
            result["revision_completed_dims"] = rev_completed

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
        structured=True,
    )


def _load_l1_fact_section(
    state: Dict[str, Any],
    *,
    dimension_key: str = "",
    source_dimensions: list[str] | None = None,
) -> tuple[str, Dict[str, Any]]:
    """Load L1 facts and build the one closed catalog used by L2."""
    ref_data = (state.get("artifact_refs") or {}).get("l1_snapshot")
    empty_catalog = empty_l1_fact_catalog()
    audit: Dict[str, Any] = {
        "fact_count": 0,
        "snapshot_ref": ref_data,
        "fact_catalog": empty_catalog,
        "catalog": empty_catalog,
        "catalog_digest": empty_catalog.digest,
        "fact_catalog_digest": empty_catalog.digest,
        "allowed_fact_ids": [],
        "spatial_fact_ids": [],
        "fact_ids": [],
    }
    if not isinstance(ref_data, dict):
        return "", audit

    try:
        from app.infrastructure.artifacts.runtime import load_artifact

        payload = load_artifact(state, "l1_snapshot")
        if hasattr(payload, "model_dump"):
            payload = payload.model_dump(mode="json")
        if not isinstance(payload, dict):
            return "", audit
        fact_records = payload.get("fact_records") or []
        location_facts = payload.get("location_facts") or []
        selected_dimensions = list(source_dimensions or [])
        if dimension_key:
            selected_dimensions.insert(0, dimension_key)
        scoped_records = [
            item
            for item in fact_records
            if (
                not selected_dimensions
                or not item.get("dimension_key")
                or item.get("dimension_key") in selected_dimensions
            )
        ]
        catalog = build_l1_fact_catalog(scoped_records)
        audit.update({
            "fact_catalog": catalog,
            "catalog": catalog,
            "catalog_digest": catalog.digest,
            "fact_catalog_digest": catalog.digest,
            "allowed_fact_ids": catalog.usable_allowed_fact_ids,
            "spatial_fact_ids": catalog.usable_spatial_fact_ids,
            # Compatibility for callers that only inspect the audit mapping;
            # this value is now canonical-only and never admits legacy IDs.
            "fact_ids": catalog.usable_allowed_fact_ids,
        })
        # The fact body is deliberately identity-free.  Only the catalog
        # below the system prompt exposes copyable fact IDs.
        facts = [
            str(item.get("statement") or "").strip()
            for item in scoped_records
            if str(item.get("statement") or "").strip()
        ]
        audit["fact_count"] = len(facts)
        audit["fact_record_count"] = len(scoped_records)
        scoped_locations = [
            item for item in location_facts
            if not selected_dimensions or item.get("dimension_key") in selected_dimensions
        ]
        audit["location_fact_count"] = len(scoped_locations)
        if not facts and not scoped_locations:
            return "", audit
        lines = [
            f"【L1 对 {dimension_key} 的上游事实（来自 L1Snapshot artifact，必须在 L2 策略中消费）】"
        ]
        lines.extend(f"- {fact}" for fact in facts)
        if scoped_locations:
            lines.append("【L1 上游地点事实（仅作为地点证据，不是选址决定）】")
            for fact in scoped_locations:
                lines.append(
                    f"- {fact.get('normalized_name') or fact.get('mention')}: "
                    f"{fact.get('spatial_hint', '')[:240]}"
                )
        return "\n".join(lines), audit
    except Exception as exc:  # fail closed for audit, preserve existing explore path
        audit["load_error"] = f"{type(exc).__name__}: {exc}"
        return "", audit


def _l2_fact_reference_rules(audit: Dict[str, Any]) -> str:
    """Render the current L1 fact catalog as the runtime closed set."""
    catalog = audit.get("fact_catalog") or audit.get("catalog")
    if not isinstance(catalog, L1FactCatalog):
        # Keep this helper deterministic for direct callers while accepting
        # only caller-supplied canonical IDs; no ID is ever derived here.
        raw_ids = audit.get("allowed_fact_ids") or audit.get("fact_ids") or []
        catalog = build_l1_fact_catalog(
            {"fact_id": value} for value in raw_ids
        )
    fact_ids = catalog.usable_allowed_fact_ids
    spatial_fact_ids = catalog.usable_spatial_fact_ids
    lines = [
        "【source_fact_refs 运行时闭集】",
        "source_fact_refs 只能逐字复制下面列出的 canonical L1Snapshot fact_id。",
        "事实正文只用于理解内容，不是可复制身份；不得自行拼接维度名、UUID、报告引用、地点名或 source_refs。",
        f"catalog_digest: {catalog.digest}",
    ]
    if fact_ids:
        lines.append("允许值：")
        lines.extend(f"- {fact_id}" for fact_id in fact_ids)
        lines.append(
            "机器可复制的 JSON 闭集："
            + json.dumps({"allowed_l1_fact_ids": fact_ids}, ensure_ascii=False)
        )
        lines.append(
            "空间事实子集（仍属于上述闭集）："
            + json.dumps({"allowed_l1_spatial_fact_ids": spatial_fact_ids}, ensure_ascii=False)
        )
        lines.extend([
            "PlanningObjective/TargetMetric 标记 observed 时至少引用一个允许值；",
            "StrategyRule 和 SpatialStructureIntent 只有在能引用允许值时才输出。",
            "没有对应事实时使用 proposed 或省略对象，不要填入近似 ID。",
        ])
    else:
        lines.append(
            "本维度没有可引用的 canonical L1 fact_id；所有 source_fact_refs 必须为 []，"
            "只能输出不需要事实引用的 proposed 规划背景或 evidence_gaps。"
        )
    return "\n".join(lines)


async def _validate_l2_decision_with_one_closed_set_reask(
    decision_set: L2DecisionSet,
    *,
    catalog: L1FactCatalog | None = None,
    catalog_digest: str = "",
    known_l1_fact_ids: set[str] | None = None,
    run_decision: Any,
) -> tuple[L2DecisionSet, str]:
    """Validate L2 once, then allow one exact-feedback provider reask.

    The reask is a contract boundary, not a repair pass: no field is edited
    locally and no reference is dropped.  A second failure is returned to the
    dimension gate so the invalid decision cannot reach report synthesis.
    """

    from app.domain.validation.l2_closure import validate_l2_decision_set

    if catalog is None:
        # Backward-compatible direct-call support for older unit tests.  The
        # production worker always passes the snapshot-derived catalog.
        catalog = build_l1_fact_catalog(
            {"fact_id": value} for value in (known_l1_fact_ids or set())
        )
    expected_catalog_digest = str(catalog_digest or catalog.digest)

    def _validate(value: L2DecisionSet) -> None:
        if expected_catalog_digest != catalog.digest:
            raise ValueError(
                "l1_fact_catalog_digest_mismatch:"
                f"expected={expected_catalog_digest}:actual={catalog.digest}"
            )
        catalog_membership = validate_l1_fact_catalog(catalog)
        if not catalog_membership.accepted:
            raise ValueError(
                "l1_fact_catalog_invalid:"
                f"missing={catalog_membership.missing_ids}:"
                f"extra={catalog_membership.extra_ids}:"
                f"duplicates={catalog_membership.duplicate_ids}"
            )
        reference_errors: list[str] = []
        for field_name in ("objectives", "metrics", "strategies", "spatial_structures"):
            for item in list(getattr(value, field_name, []) or []):
                membership = validate_l1_fact_references(
                    getattr(item, "source_fact_refs", []) or [],
                    catalog=catalog,
                )
                if not membership.accepted:
                    owner_id = str(
                        getattr(item, "objective_id", "")
                        or getattr(item, "metric_id", "")
                        or getattr(item, "strategy_id", "")
                        or getattr(item, "structure_id", "")
                        or "unknown"
                    )
                    reference_errors.append(
                        f"{field_name}:{owner_id}:catalog_digest={catalog.digest}:"
                        f"extra={membership.extra_ids}:duplicates={membership.duplicate_ids}"
                    )
        if reference_errors:
            raise ValueError("\n".join(reference_errors))
        validate_l2_decision_set(
            value,
            known_l1_fact_ids=set(catalog.usable_allowed_fact_ids),
        )

    try:
        _validate(decision_set)
        return decision_set, ""
    except ValueError as first_error:
        first_message = str(first_error).splitlines()[0][:1000]

    retried = await run_decision(
        "L2 fact catalog must remain unchanged for this reask. "
        f"catalog_digest={catalog.digest}; "
        "allowed_l1_fact_ids="
        f"{json.dumps(catalog.usable_allowed_fact_ids, ensure_ascii=False)}\n"
        + first_message
    )
    retried = retried.model_copy(update={"dimension_key": decision_set.dimension_key})
    try:
        _validate(retried)
    except ValueError as second_error:
        second_message = str(second_error).splitlines()[0][:1000]
        return retried, (
            "L2_SOURCE_FACT_CLOSED_SET_FAILED: "
            f"first={first_message}; retry={second_message}"
        )
    return retried, ""


def _build_l2_report_synthesis_prompt(
    dimension_key: str,
    decision_set: L2DecisionSet,
) -> str:
    """Build the independent human-report projection prompt for L2."""
    decision_json = decision_set.model_dump_json(ensure_ascii=False)
    return (
        f"【L2 report synthesis pass; dimension_key={dimension_key}】\n"
        "你只负责生成人类规划人员阅读的规划思路正文，输出 L2ReportOutput。"
        "正文只能解释下面已经通过 L2DecisionSet 结构和语义闭合校验的决策；"
        "不得新增目标、指标、数量、位置、关系、空间身份、来源事实或执行几何。"
        "空数组表示本维度没有该类内容，不得用模板或常识补写。"
        "只返回 report_body 字段，不返回决策 JSON、Markdown 代码围栏或其他根字段。\n\n"
        f"【validated L2DecisionSet】\n{decision_json}\n\n"
        "请将已验证的决策组织为连贯、简洁、可供人阅读的规划思路正文。"
    )


def _require_l2_report_body(value: Any) -> str:
    report_body = str(value or "").strip()
    if not report_body:
        raise ValueError("L2_REPORT_BODY_EMPTY")
    return report_body


def _dependency_summary(text: str) -> Dict[str, Any]:
    """Compact audit view; the full dependency prose remains prompt input."""
    import re

    return {
        "sections": re.findall(r"【([^】]+)】", text or ""),
        "chars": len(text or ""),
        "preview": (text or "")[:500],
    }


def _decision_summary_json(decision: L2DecisionSet, report_body: str) -> str:
    payload = {
        "dimension_key": decision.dimension_key,
        "layer": 2,
        "word_count": len(report_body),
        "key_points": [
            item.statement
            for item in [*decision.objectives, *decision.strategies]
            if str(getattr(item, "statement", "") or "").strip()
        ][:8],
        "metrics": {
            item.name: {"value": item.value, "unit": item.unit, "status": item.status}
            for item in decision.metrics
            if item.name.strip()
        },
        "decision_counts": {
            "objectives": len(decision.objectives),
            "metrics": len(decision.metrics),
            "strategies": len(decision.strategies),
            "priorities": len(decision.priorities),
            "spatial_structures": len(decision.spatial_structures),
            "conflicts": len(decision.conflicts),
            "evidence_gaps": len(decision.evidence_gaps),
        },
    }
    return json.dumps(payload, ensure_ascii=False)


__all__ = ["analyze_l2_dimension", "_decision_summary_json"]
