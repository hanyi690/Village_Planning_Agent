"""L3 PLAN dimension worker - analyze_l3_dimension.

Independent L3-only dimension analysis worker (Wave E). Mirrors the shared
L1/L2 dimension flow but is restricted to the L3 detail-planning layer and
reuses the shared runtime helpers from ``app.infrastructure.llm.dimension_runtime``.
Per docs/architecture/agent-graph.md the L3 subgraph is independent and must
not reference the L1 analysis node implementation.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import time
import uuid
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from langchain_core.messages import AIMessage

from app.config import get_dimension_config
from app.contracts.events import SSEEventType
from app.core.settings import LLM_STREAM_TIMEOUT
from app.infrastructure.logging import get_logger
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
from app.infrastructure.llm.prompts.detailed import get_dimension_prompt as get_layer3_prompt
from app.contracts.evidence.evidence_contracts import ExplorationRequest
from app.contracts.program import PlanningClaimSet
from app.infrastructure.tasks.task_supervisor import build_summary_task_key

logger = get_logger(__name__)


def _claim_cache_path(session_id: str, dimension_key: str, prompt: str) -> Path:
    """Return the content-addressed cache path for one provider invocation."""
    from app.infrastructure.paths import session_run_dir

    digest = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    return (
        session_run_dir(session_id)
        / "l3-claim-cache"
        / dimension_key
        / f"{digest}.json"
    )


async def _cached_claim_generation(
    generator: Any,
    *,
    session_id: str,
    dimension_key: str,
    prompt: str,
    validation_feedback: list[str] | None = None,
):
    """Generate a draft set once and replay it on checkpoint resume.

    The key contains the complete prompt, including validator feedback for a
    local repair.  A valid provider response is persisted before downstream
    compilation so an interrupted graph can resume L3 without paying for the
    same model call again.
    """
    from app.domain.program.claim_draft import L3DimensionOutput

    schema_payload = L3DimensionOutput.model_json_schema()
    schema_checksum = hashlib.sha256(
        json.dumps(schema_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    cache_key = json.dumps(
        {
            "prompt": prompt,
            "validation_feedback": validation_feedback or [],
            "schema_checksum": schema_checksum,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    path = _claim_cache_path(session_id, dimension_key, cache_key)
    if path.exists():
        try:
            cached = L3DimensionOutput.model_validate_json(
                path.read_text(encoding="utf-8")
            )
            logger.info(
                "[analyze_l3_dimension] %s: claim cache HIT %s",
                dimension_key,
                path.name,
            )
            return cached
        except (OSError, ValueError):
            logger.warning(
                "[analyze_l3_dimension] %s: ignoring invalid claim cache %s",
                dimension_key,
                path,
            )

    generated = await generator.generate(
        prompt,
        validation_feedback=validation_feedback,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f".{uuid.uuid4().hex}.tmp")
    temporary.write_text(generated.model_dump_json(indent=2), encoding="utf-8")
    os.replace(temporary, path)
    logger.info(
        "[analyze_l3_dimension] %s: claim cache WRITE %s",
        dimension_key,
        path.name,
    )
    return generated


# Cached LLM instance — reused across all L3 dimension analyses
def _build_revision_completed(state: Dict[str, Any], dim_key: str) -> Dict[int, list]:
    """根据 impact_tree 反查维度所属 wave，构建 revision_completed_dims 更新"""
    impact_tree = state.get("revision_impact_tree", {})
    result: Dict[int, list] = {}
    for wave, dims in impact_tree.items():
        if dim_key in dims:
            result[wave] = [dim_key]
    return result


def _location_evidence(text: str) -> str:
    """Extract compact, source-backed location rows for the L3 prompt.

    The complete dependency reports remain in the prompt.  This separate
    block makes the spatial provenance decision explicit and prevents the
    model from turning a village list into an unsupported project location.
    """
    rows: List[str] = []
    seen: set[str] = set()
    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if not any(token in line for token in ("位于", "分布", "涉及", "集中", "位置", "布局")):
            continue
        if line in seen:
            continue
        seen.add(line)
        rows.append(line[:320])
        if len(rows) >= 60:
            break
    return "\n".join(f"- {row}" for row in rows) or "（依赖报告未提供可核验的对象—地点位置关系）"


def _resolvable_places(session_id: str) -> str:
    """Return gazetteer place aliases backed by real BSM evidence.

    This intentionally includes roads, water bodies, facilities, settlements,
    administrative units and other registered place entities.  The L3 source
    contract must not collapse spatial evidence to a hard-coded village list.
    """
    try:
        from app.infrastructure.context.planning_context_factory import get_cached_context

        context = get_cached_context(session_id)
        names: List[str] = []
        for entry in (getattr(getattr(context, "gazetteer", None), "entries", []) or []):
            if not getattr(entry, "bsms", None):
                continue
            name = str(getattr(entry, "name", "") or "")
            if name and name not in names:
                names.append(name)
            if len(names) >= 200:
                break
        return "、".join(names)
    except Exception:
        return ""


def _structural_repair_prompt(dimension_key: str, error: Any) -> str:
    """Bounded repair prompt for a claim set that fails schema validation.

    The provider's structured output sometimes violates a closed-set literal
    (e.g. facility action ``upgrade``).  Instead of hard-failing the dimension,
    the exact validation error is fed back so the provider can repair it.
    """
    return (
        "你是 L3 Claim 结构修复器。上一轮结构化输出未通过 schema 校验。"
        "按下列校验错误修复整个 claims 数组（report_body 留空），"
        "不得新增 claim 或改写 claim_id，不得创建坐标/BSM/地块/几何；"
        "枚举字段必须使用声明值。\n"
        f"dimension={dimension_key}\n"
        f"validation_error={str(error)[:3000]}"
    )


async def _normalize_with_structural_repair(
    claim_generator: Any,
    *,
    session_id: str,
    dimension_key: str,
    output: Any,
) -> tuple[Any, PlanningClaimSet]:
    """Normalize a claim set, retrying with feedback on schema validation errors.

    A structurally invalid provider response (closed-set literal violation) is
    re-requested up to ``L3_STRUCTURAL_COMPILE_RETRIES`` times with the exact
    error; only after the budget is exhausted does the exception propagate to
    the caller's fatal-error path.  Single-candidate deterministic, no geometry
    or BSM is ever created here.
    """
    from pydantic import ValidationError

    from app.domain.program.claim_draft import (
        PlanningClaimDraftSet,
        normalize_claim_draft_set,
    )

    structural_retries = max(
        0,
        int(os.getenv("L3_STRUCTURAL_COMPILE_RETRIES", "2")),
    )
    current_output = output
    for attempt in range(structural_retries + 1):
        try:
            draft_set = PlanningClaimDraftSet(
                dimension_key=dimension_key,
                claims=list(current_output.claims),
            )
            claim_set = normalize_claim_draft_set(draft_set, dimension_key=dimension_key)
            return draft_set, claim_set
        except (ValidationError, TypeError, ValueError) as exc:
            if attempt >= structural_retries:
                raise
            logger.warning(
                "[analyze_l3_dimension] %s: structural repair round %d: %s",
                dimension_key,
                attempt + 1,
                str(exc)[:600],
            )
            current_output = await _cached_claim_generation(
                claim_generator,
                session_id=session_id,
                dimension_key=dimension_key,
                prompt=_structural_repair_prompt(dimension_key, exc),
                validation_feedback=[str(exc)],
            )
    raise RuntimeError("unreachable: structural repair budget exhausted")


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
    from app.infrastructure.reports.report_store import ReportStore

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
        resolvable_villages=_resolvable_places(session_id),
    )
    logger.info(f"[analyze_l3_dimension] {dim_key}: Prompt length = {len(prompt)} chars")

    # 5.5 统计收集 - 开始维度
    from app.infrastructure.llm.stats_collector import StatsCollector
    stats = StatsCollector.get_instance()
    stats.start_dimension(session_id, dim_key, dim_name, dim_layer)
    stats.record_prompt(session_id, dim_key, len(prompt))
    if rag_log:
        stats.record_rag_time(session_id, dim_key, rag_log.retrieval_latency_ms, rag_log.total_results)

    # 6. 流式 LLM + SSE
    from app.domain.program.claim_draft import (
        PlanningClaimDraftSet,
        claim_set_semantic_errors,
        merge_repaired_claim_drafts,
        normalize_claim_draft_set,
        semantic_error_claim_ids,
    )
    from app.infrastructure.llm import get_planning_claim_generator

    claim_generator = get_planning_claim_generator()
    if provider_failure_open(session_id):
        return {
            "dimension_retry_counts": dimension_failure_attempt(state, dim_key),
            "dimension_retry_counts": dimension_failure_attempt(state, dim_key),
            "provider_failures": [{
                "stage": f"L{dim_layer}", "dimension": dim_key,
                "code": "llm_provider_circuit_open",
                "message": "LLM provider circuit is open after a prior session failure",
            }],
        }
    llm_start_time = time.time()

    claim_set: PlanningClaimSet | None = None
    llm_response = ""

    try:
        # Queueing for the bounded provider semaphore is not an LLM stream
        # timeout.  Each actual provider invocation owns its timeout after it
        # acquires a slot inside PlanningClaimGenerator.
        output = await _cached_claim_generation(
            claim_generator,
            session_id=session_id,
            dimension_key=dim_key,
            prompt=prompt,
        )
        report_body = (output.report_body or "").strip()
        draft_set, claim_set = await _normalize_with_structural_repair(
            claim_generator,
            session_id=session_id,
            dimension_key=dim_key,
            output=output,
        )
        if not draft_set.claims and not report_body:
            draft_set.diagnostics.append("provider returned no structured claim set")
        semantic_feedback = claim_set_semantic_errors(claim_set)
        semantic_retry_count = max(
            0,
            int(os.getenv("L3_SEMANTIC_COMPILE_RETRIES", "2")),
        )
        for semantic_attempt in range(semantic_retry_count):
            if not semantic_feedback:
                break
            rejected_ids = semantic_error_claim_ids(semantic_feedback)
            rejected = [
                item.model_dump(mode="json")
                for item in draft_set.claims
                if item.claim_id in set(rejected_ids)
            ]
            if not rejected:
                break
            logger.warning(
                "[analyze_l3_dimension] %s: local semantic repair round %d claims=%s errors=%s",
                dim_key,
                semantic_attempt + 1,
                rejected_ids,
                semantic_feedback[:8],
            )
            repair_prompt = (
                "你是 L3 Claim 局部语义编译修复器。只返回下列失败 claim 的完整"
                "claims 数组（report_body 留空），不得返回已通过 claim，不得新增、删除或改写 claim_id。"
                "不得创建坐标、BSM、地块或几何。严格按对象参数 schema 修复。"
                "category/output/phase、各对象 action、axis_type、materialization_role "
                "必须从工具 schema 的 enum 中选择；不得发明同义词。"
                "只修改 validator_errors 明确指出的字段，其余字段保持原值。\n"
                f"dimension={dim_key}\n"
                f"validator_errors={json.dumps(semantic_feedback, ensure_ascii=False)}\n"
                f"rejected_claims={json.dumps(rejected, ensure_ascii=False)}"
            )
            repair_output = await _cached_claim_generation(
                claim_generator,
                session_id=session_id,
                dimension_key=dim_key,
                prompt=repair_prompt,
                validation_feedback=semantic_feedback,
            )
            draft_set = merge_repaired_claim_drafts(
                draft_set,
                PlanningClaimDraftSet(
                    dimension_key=dim_key,
                    claims=list(repair_output.claims),
                ),
                rejected_ids,
            )
            claim_set = normalize_claim_draft_set(
                draft_set,
                dimension_key=dim_key,
            )
            semantic_feedback = claim_set_semantic_errors(claim_set)
        if claim_set is not None and semantic_feedback:
            claim_set.diagnostics.append(
                "ERROR[semantic_compile_exhausted] "
                f"{dim_key}: bounded local repair exhausted; "
                + "; ".join(semantic_feedback[:20])
            )
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
            "provider_failures": [{
                "stage": f"L{dim_layer}", "dimension": dim_key,
                "code": "llm_stream_timeout",
                "message": f"LLM stream timeout ({LLM_STREAM_TIMEOUT}s)",
            }],
        }
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        # LLM output quality failure: the provider returned malformed /
        # truncated structured JSON (PlanningClaimGenerator retried with the
        # parse error as feedback and exhausted its budget).  This is NOT a
        # provider infrastructure failure: tripping the session circuit here
        # would block every other dimension of the layer.  Keep the transient
        # code ``llm_provider_error`` so the existing HUMAN/provider-resume
        # path can retry exactly this one dimension with a bounded budget.
        logger.error(
            "[analyze_l3_dimension] %s: structured output failed to parse: %s",
            dim_key,
            str(exc)[:600],
        )
        await sse_manager.publish(session_id, {
            "type": SSEEventType.DIMENSION_ERROR,
            "dimension_key": dim_key,
            "dimension_name": dim_name,
            "layer": dim_layer,
            "error": f"structured output failed to parse: {exc}",
        })
        return {
            "messages": [AIMessage(content=f"[执行失败] 结构化输出解析失败: {exc}")],
            "dimension_retry_counts": dimension_failure_attempt(state, dim_key),
            "provider_failures": [{
                "stage": f"L{dim_layer}", "dimension": dim_key,
                "code": "llm_provider_error",
                "message": f"L3 structured output failed to parse: {exc}",
            }],
        }
    except Exception as e:
        # Genuine provider infrastructure failure (transport/HTTP/circuit).
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
            "provider_failures": [{
                "stage": f"L{dim_layer}", "dimension": dim_key,
                "code": "llm_provider_error", "message": str(e),
            }],
        }

    if claim_set is None:
        raise RuntimeError(f"L3 claim generation returned no result for {dim_key}")
    claim_set.dimension_key = dim_key
    claim_set.claims = [
        claim.model_copy(update={"dimension_key": claim.dimension_key or dim_key})
        for claim in claim_set.claims
    ]
    claims_json = claim_set.model_dump_json(indent=2)
    llm_response = report_body or claims_json
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
        "content": report_body,
        "instruction": claims_json,
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
    display = (text or "").strip()
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
        from app.infrastructure.context.planning_context_factory import get_cached_context

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

    # Quality-retry instruction: the previous run exhausted semantic repair;
    # re-prompt with the exact validator errors so the LLM avoids them from
    # the start instead of repeating the bad output.
    quality_feedback = str(state.get("quality_feedback") or "").strip()
    if quality_feedback:
        quality_instruction = (
            "【编译修正指令】上次输出的干预项目未通过 schema 编译，错误如下，"
            "请在本次生成中严格规避：\n"
            f"\"{quality_feedback}\""
        )
        revision_instruction = (
            revision_instruction + "\n\n" + quality_instruction
            if revision_instruction
            else quality_instruction
        )

    return get_layer3_prompt(
        dimension_key=dim_key,
        project_name=project_name,
        analysis_report=l1_deps,
        planning_concept=l2_deps,
        constraints=constraints,
        knowledge_context=rag_context or "",
        revision_instruction=revision_instruction,
        professional_data_section=professional_data_section + explore_section,
        natural_villages=resolvable_villages,
        location_evidence=_location_evidence(l1_deps + "\n" + l2_deps),
        dimension_plans=same_layer_contexts,
    )


__all__ = ["analyze_l3_dimension"]
