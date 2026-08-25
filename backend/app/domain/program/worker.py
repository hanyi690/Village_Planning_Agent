"""L3 PLAN dimension worker - analyze_l3_dimension.

Independent L3-only dimension analysis worker (Wave E). Mirrors the shared
L1/L2 dimension flow but is restricted to the L3 detail-planning layer and
reuses the shared runtime helpers from ``app.infrastructure.llm.dimension_runtime``.
Per docs/architecture/CURRENT_RUNTIME.md the L3 subgraph is independent and must
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
from typing import Any, Dict, Iterable, List

from langchain_core.messages import AIMessage

from app.config import get_dimension_config
from app.contracts.events import SSEEventType
from app.core.settings import LLM_STREAM_TIMEOUT
from app.infrastructure.logging import get_logger
from app.infrastructure.llm.dimension_runtime import (
    load_layered_dependency_reports,
    publish_dimension_complete,
    publish_dimension_delta,
    publish_dimension_start,
    provider_failure_open,
    trip_provider_failure,
    is_provider_failure,
    is_provider_quota_exhausted,
    dimension_failure_attempt,
    run_rag,
    save_report_immediate,
    save_step_report,
    strip_model_reasoning,
)
from app.infrastructure.llm.prompts.detailed import get_dimension_prompt as get_layer3_prompt
from app.contracts.program import PlanningClaimSet

logger = get_logger(__name__)


class L3ReportBodyEmptyError(ValueError):
    """Provider returned executable claims but no human-facing report body."""


def _claim_lineage_present(claim: Any) -> bool:
    """Return whether a claim carries any declared source lineage."""

    return bool(
        getattr(claim, "evidence_refs", None)
        or getattr(claim, "source_fact_refs", None)
        or getattr(claim, "source_refs", None)
    )


def _require_l3_report_body(value: Any) -> str:
    report_body = str(value or "").strip()
    if not report_body:
        raise L3ReportBodyEmptyError(
            "L3_REPORT_BODY_EMPTY: provider returned structured claims without "
            "the required human-readable report_body"
        )
    return report_body


def _projection_cache_path(
    session_id: str,
    dimension_key: str,
    prompt: str,
    projection: str,
) -> Path:
    """Content-address one single-purpose L3 projection."""

    from app.infrastructure.paths import session_run_dir

    digest = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    return (
        session_run_dir(session_id)
        / "l3-projection-cache"
        / projection
        / dimension_key
        / f"{digest}.json"
    )


async def _cached_claim_only_generation(
    generator: Any,
    *,
    session_id: str,
    dimension_key: str,
    prompt: str,
    validation_feedback: list[str] | None = None,
):
    """Generate or resume the claims-only L3 projection."""

    from app.domain.program.claim_draft import L3ClaimOutput

    cache_key = json.dumps(
        {
            "prompt": prompt,
            "validation_feedback": validation_feedback or [],
            "schema_checksum": hashlib.sha256(
                json.dumps(
                    L3ClaimOutput.model_json_schema(),
                    ensure_ascii=False,
                    sort_keys=True,
                ).encode("utf-8")
            ).hexdigest(),
            "cache_contract": "l3-claims-only-v1",
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    path = _projection_cache_path(session_id, dimension_key, cache_key, "claims")
    if path.exists():
        try:
            return L3ClaimOutput.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            logger.warning("[analyze_l3_dimension] ignoring invalid claims cache %s", path)
    generate_claims = getattr(generator, "generate_claims", None)
    if not callable(generate_claims):
        raise TypeError("L3 claims generator must expose generate_claims()")
    generated = await generate_claims(
        prompt,
        validation_feedback=validation_feedback,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f".{uuid.uuid4().hex}.tmp")
    temporary.write_text(generated.model_dump_json(indent=2), encoding="utf-8")
    os.replace(temporary, path)
    return generated


async def _cached_report_generation(
    generator: Any,
    *,
    session_id: str,
    dimension_key: str,
    prompt: str,
):
    """Generate or resume the report-only L3 projection."""

    from app.domain.program.claim_draft import L3ReportOutput

    cache_key = json.dumps(
        {
            "prompt": prompt,
            "schema_checksum": hashlib.sha256(
                json.dumps(
                    L3ReportOutput.model_json_schema(),
                    ensure_ascii=False,
                    sort_keys=True,
                ).encode("utf-8")
            ).hexdigest(),
            "cache_contract": "l3-report-only-v1",
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    path = _projection_cache_path(session_id, dimension_key, cache_key, "report")
    if path.exists():
        try:
            return L3ReportOutput.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            logger.warning("[analyze_l3_dimension] ignoring invalid report cache %s", path)
    generate_report = getattr(generator, "generate_report", None)
    if not callable(generate_report):
        raise TypeError("L3 report generator must expose generate_report()")
    generated = await generate_report(prompt)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f".{uuid.uuid4().hex}.tmp")
    temporary.write_text(generated.model_dump_json(indent=2), encoding="utf-8")
    os.replace(temporary, path)
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


def _l3_source_dimensions(cfg: Any, dimension_key: str) -> set[str]:
    """Return the typed L1 dimensions that may support one L3 dimension."""

    configured = getattr(cfg, "layer_depends_on", ()) or ()
    return {
        str(value).strip()
        for value in configured
        if str(value).strip()
    } | {str(dimension_key or "").strip(), "location", "spatial", ""}


def _bounded_prompt_attributes(value: Any) -> dict[str, str]:
    """Keep prompt attributes useful without letting one fact consume context."""

    if not isinstance(value, dict):
        return {}
    rows: dict[str, str] = {}
    for key in sorted(value, key=lambda item: str(item))[:8]:
        item = value[key]
        if isinstance(item, (dict, list, tuple, set)):
            item = json.dumps(item, ensure_ascii=False, default=str)
        text = str(item or "").strip()
        if text:
            rows[str(key)] = text[:180]
    return rows


def _typed_l1_fact_evidence(
    state: Dict[str, Any],
    dimension_key: str,
    *,
    location_only: bool = False,
    source_dimensions: Iterable[str] | None = None,
) -> str:
    """Render bounded typed L1 facts for the L3 prompt.

    L3 must not infer spatial relations by scanning prose for words such as
    ``位于`` or ``布局``.  L1Fact/L1LocationFact carry semantic type, subject
    scope, source refs and (when available) source feature IDs; those typed
    records are the only machine source used here.  The report body remains a
    human-readable projection and is intentionally not used as a location
    index.
    """
    try:
        from app.infrastructure.context.planning_context_factory import get_cached_context

        context = get_cached_context(str(state.get("session_id", "")))
    except Exception:
        context = None
    if context is None:
        return "（当前上下文没有可用的 L1 spatial evidence；不得据此创建空间 claim。）"

    allowed_dimensions = {
        str(value).strip()
        for value in (source_dimensions or (dimension_key, "location", "spatial", ""))
        if str(value).strip() or value == ""
    }
    if location_only:
        rows: list[dict[str, Any]] = []
        for item in list(getattr(context, "location_facts", []) or []):
            fact_dimension = str(getattr(item, "dimension_key", "") or "").strip()
            if fact_dimension not in allowed_dimensions:
                continue
            mention = str(getattr(item, "mention", "") or "").strip()
            normalized_name = str(getattr(item, "normalized_name", "") or "").strip()
            if not mention and not normalized_name:
                continue
            rows.append({
                "mention": mention,
                "normalized_name": normalized_name,
                "role": str(getattr(item, "role", "") or ""),
                "dimension_key": fact_dimension,
                "spatial_hint": str(getattr(item, "spatial_hint", "") or ""),
                "related_mentions": list(getattr(item, "related_mentions", []) or []),
                "evidence_refs": list(getattr(item, "evidence_refs", []) or []),
                "source_report_ref": str(getattr(item, "source_report_ref", "") or ""),
            })
            if len(rows) >= 24:
                break
        if not rows:
            return "（当前 L1 没有带证据引用的 L1 spatial location facts；不得从地点名单推断对象位置。）"
        return "【已审计 L1 spatial location facts】\n" + json.dumps(
            rows, ensure_ascii=False, indent=2
        )

    facts: list[Any] = []
    for fact in list(getattr(context, "l1_fact_records", []) or []):
        fact_dimension = str(getattr(fact, "dimension_key", "") or "").strip()
        if fact_dimension not in allowed_dimensions:
            continue
        statement = str(getattr(fact, "statement", "") or "").strip()
        fact_id = str(getattr(fact, "fact_id", "") or "").strip()
        if not statement or not fact_id:
            continue
        facts.append(fact)

    source_dimension_order = {
        str(value): index
        for index, value in enumerate(
            str(value).strip()
            for value in (source_dimensions or (dimension_key,))
            if str(value).strip()
        )
    }
    spatial_kinds = {"spatial_observation", "gis_observation", "kg_canonical_fact"}

    # Prefer identity-bearing spatial facts, then configured upstream facts.
    # This is a stable typed ordering, not a text score.
    facts.sort(key=lambda fact: (
        0 if str(getattr(fact, "fact_kind", "") or "") in spatial_kinds else 1,
        source_dimension_order.get(
            str(getattr(fact, "dimension_key", "") or ""),
            len(source_dimension_order),
        ),
        0 if list(getattr(fact, "source_feature_ids", []) or []) else 1,
        str(getattr(fact, "fact_id", "")),
    ))
    rows = []
    for fact in facts[:48]:
        rows.append({
            "fact_id": str(getattr(fact, "fact_id", "") or ""),
            "statement": str(getattr(fact, "statement", "") or "")[:360],
            "fact_kind": str(getattr(fact, "fact_kind", "") or ""),
            "dimension_key": str(getattr(fact, "dimension_key", "") or ""),
            "semantic_type": str(getattr(fact, "semantic_type", "") or ""),
            "subject_scope": str(getattr(fact, "subject_scope", "") or ""),
            "attributes": _bounded_prompt_attributes(
                getattr(fact, "attributes", {})
            ),
            "source_refs": list(getattr(fact, "source_refs", []) or []),
            "source_feature_ids": list(getattr(fact, "source_feature_ids", []) or []),
            "source_snapshot_ref": str(getattr(fact, "source_snapshot_ref", "") or ""),
        })
    if not rows:
        return "（当前上下文没有可用的 L1 typed facts；不得据此创建空间 claim。）"
    return (
        "【已审计 L1 planning facts】\n"
        "这些记录是当前 L1 快照的权威结构化事实。非空间 claim 可引用对应 fact_id；"
        "空间 claim 的 source_fact_refs 只能逐字引用 fact_kind=spatial_observation/gis_observation 的记录；"
        "source_feature_ids 只用于说明可由后续 EvidenceGraph 继续连接，不能在 L3 直接当作几何。\n"
        + json.dumps(rows, ensure_ascii=False, indent=2)
    )


def _spatial_claim_evidence_errors(
    state: Dict[str, Any],
    claim_set: PlanningClaimSet,
) -> list[str]:
    """Reject spatial claims that cite foreign L1 fact identities.

    This is an exact identity check, not a name/regex matcher. A spatial claim
    without source_fact_refs is a valid semantic candidate and must continue
    to GROUND, where EvidenceGraph resolves its location. If the model does
    provide source_fact_refs, every id must exist in the hydrated L1 context;
    a foreign id enters the bounded repair loop. Whether a location hint
    semantically matches a fact remains an LLM/EvidenceGraph responsibility.
    """
    spatial_kinds = {"parcel", "polygon", "point", "line"}
    claims = list(getattr(claim_set, "claims", []) or [])
    if not any(
        getattr(claim, "suggested_output_kind", "") in spatial_kinds
        for claim in claims
    ):
        return []
    try:
        from app.infrastructure.context.planning_context_factory import get_cached_context

        context = get_cached_context(str(state.get("session_id", "")))
    except Exception:
        context = None
    fact_ids = {
        str(getattr(fact, "fact_id", "") or "")
        for fact in (getattr(context, "l1_fact_records", []) or [])
        if str(getattr(fact, "fact_id", "") or "")
        and str(getattr(fact, "fact_kind", "") or "")
        in {"spatial_observation", "gis_observation", "kg_canonical_fact"}
    }
    errors: list[str] = []
    for claim in claims:
        if getattr(claim, "suggested_output_kind", "") not in spatial_kinds:
            continue
        claim_id = str(getattr(claim, "claim_id", "") or "claim")
        refs = [
            str(ref).strip()
            for ref in (getattr(claim, "source_fact_refs", []) or [])
            if str(ref).strip()
        ]
        if not refs:
            continue
        unknown = sorted(set(refs) - fact_ids)
        if unknown:
            errors.append(
                f"ERROR[spatial_claim_unknown_fact] {claim_id}: "
                f"source_fact_refs are not present in the hydrated L1 snapshot: {unknown}"
            )
    return list(dict.fromkeys(errors))


def _compact_prompt_background(text: str, limit: int, label: str) -> str:
    """Bound report context without pretending truncation is evidence."""
    value = str(text or "").strip()
    if not value:
        return f"（{label}没有可用正文；不得据此补造事实。）"
    if len(value) <= limit:
        return value
    return (
        value[:limit]
        + f"\n\n【{label}已截断】仅保留前 {limit} 个字符作为背景；"
        "被截断内容不是可引用的空间证据。"
    )


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
        "按下列校验错误只修复整个 claims 数组，不返回 report_body，"
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
        int(os.getenv("L3_STRUCTURAL_COMPILE_RETRIES", "0")),
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
            current_output = await _cached_claim_only_generation(
                claim_generator,
                session_id=session_id,
                dimension_key=dimension_key,
                prompt=_structural_repair_prompt(dimension_key, exc),
                validation_feedback=[str(exc)],
            )
    raise RuntimeError("unreachable: structural repair budget exhausted")


def _build_l3_report_synthesis_prompt(
    dimension_key: str,
    planning_prompt: str,
    claim_set: PlanningClaimSet,
    semantic_feedback: list[str] | None = None,
) -> str:
    """Build a report-only prompt from claims that already passed validation."""

    claims_payload = json.dumps(
        [item.model_dump(mode="json") for item in claim_set.claims],
        ensure_ascii=False,
        sort_keys=True,
    )
    feedback = json.dumps(
        list(semantic_feedback or []),
        ensure_ascii=False,
    )
    return (
        f"【L3 report synthesis; dimension_key={dimension_key}】\n"
        "你只负责生成人类规划人员阅读的 report_body，不负责重新生成 claims。"
        "正文只能解释已通过确定性 schema、source lineage 和语义校验的 claims；"
        "不得新增目标、数量、位置、关系、地块、路线或来源事实。"
        "被诊断或未通过的 claim 必须写成待核验/延期，不得把它写成已确定规划安排。"
        "只返回 report_body 字段，不返回 claims 数组、JSON 调试对象或代码围栏。\n\n"
        f"【validated claims】\n{claims_payload}\n"
        f"【claim diagnostics】\n{feedback}\n"
        f"【original evidence and planning context】\n{planning_prompt}"
    )


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

    # L3 prompts consume the same typed L1 snapshot that GROUND later uses.
    # Hydrate it before retrieval so the unified Evidence service can join
    # current L1 facts, KG topology and Bundle identity in this request.
    # Running retrieval first could query an empty cold context and then
    # report a misleading evidence-free L3 prompt.
    from app.workflow.stages.support import _require_context

    await _require_context(state)

    # 2. Unified typed evidence retrieval (REPORT/L1/KG/BUNDLE/RAG adapters).
    evidence_trace: dict[str, Any] = {}
    rag_context, rag_log = await run_rag(
        dim_key,
        cfg,
        state,
        trace_sink=evidence_trace,
    )

    # 3. 从数据库加载分层依赖报告（同层 + L1/L2 跨层分开）
    store = ReportStore.get_instance()
    l1_deps, l2_deps, same_layer_contexts = await load_layered_dependency_reports(
        dim_key, cfg, dim_layer, session_id, is_revision,
    )

    # run_rag is the unified EvidenceBundle adapter; no second retrieval call.
    explore_section = ""

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
        claim_draft_semantic_errors,
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
        output = await _cached_claim_only_generation(
            claim_generator,
            session_id=session_id,
            dimension_key=dim_key,
            prompt=prompt,
        )
        draft_set, claim_set = await _normalize_with_structural_repair(
            claim_generator,
            session_id=session_id,
            dimension_key=dim_key,
            output=output,
        )
        # Flash unit repair: unknown units (hm, ??, count-units-as-area) are
        # cheap to fix with a flash LLM - no full re-generation needed.
        try:
            from app.domain.program.flash_unit_repair import flash_repair_units

            repaired = await flash_repair_units(draft_set, session_id)
            if repaired is not None and repaired is not draft_set:
                draft_set = repaired
            from app.domain.program.claim_draft import normalize_claim_draft_set

            claim_set = normalize_claim_draft_set(draft_set, dimension_key=dim_key)
        except Exception as exc:  # noqa: BLE001 - flash repair must never break L3
            logger.warning("[analyze_l3_dimension] %s: flash unit repair failed: %s", dim_key, exc)
        semantic_feedback = [
            *claim_draft_semantic_errors(draft_set),
            *claim_set_semantic_errors(claim_set),
            *_spatial_claim_evidence_errors(state, claim_set),
        ]
        semantic_retry_count = max(
            0,
            int(os.getenv("L3_SEMANTIC_COMPILE_RETRIES", "1")),
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
            normalization_diagnostics = [
                str(item)
                for item in claim_set.diagnostics
                if any(f" {claim_id}:" in str(item) for claim_id in rejected_ids)
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
            repair_evidence = _typed_l1_fact_evidence(
                state,
                dim_key,
                source_dimensions=_l3_source_dimensions(cfg, dim_key),
            )
            repair_prompt = (
                "你是 L3 Claim 局部语义编译修复器。只返回下列失败 claim 的完整"
                "claims 数组，不得返回 report_body、不得返回已通过 claim，不得新增、删除或改写 claim_id。"
                "不得创建坐标、BSM、地块或几何。严格按对象参数 schema 修复。"
                "category/output/phase、各对象 action、axis_type、materialization_role "
                "必须从工具 schema 的 enum 中选择；不得发明同义词。"
                "跨字段必须同时满足：sewer/water_supply/stormwater/power/communication/"
                "drainage_channel/revetment 使用 road+line+linear_parameters，asset_kind=road "
                "使用 road+line+road_parameters；action+line+sewer 是非法组合，不能把线性 claim "
                "降级为 action。"
                "只修改 validator_errors 明确指出的字段，其余字段保持原值。\n"
                f"dimension={dim_key}\n"
                f"validator_errors={json.dumps(semantic_feedback, ensure_ascii=False)}\n"
                f"normalization_diagnostics={json.dumps(normalization_diagnostics, ensure_ascii=False)}\n"
                f"rejected_claims={json.dumps(rejected, ensure_ascii=False)}\n"
                "可使用的已审计 L1 spatial facts（source_fact_refs 只能逐字复制其中的 fact_id；"
                "若没有 L1 fact，保留语义 location_hints 并交给 GROUND 检索，不得编造 fact_id）：\n"
                f"{repair_evidence}"
            )
            repair_output = await _cached_claim_only_generation(
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
            semantic_feedback = [
                *claim_draft_semantic_errors(draft_set),
                *claim_set_semantic_errors(claim_set),
                *_spatial_claim_evidence_errors(state, claim_set),
            ]
        if claim_set is not None and semantic_feedback:
            claim_set.diagnostics.append(
                "ERROR[semantic_compile_exhausted] "
                f"{dim_key}: bounded local repair exhausted; "
                + "; ".join(semantic_feedback[:20])
            )
        if claim_set is None:
            raise ValueError("L3 claim projection returned no validated claim set")
        report_output = await _cached_report_generation(
            claim_generator,
            session_id=session_id,
            dimension_key=dim_key,
            prompt=_build_l3_report_synthesis_prompt(
                dim_key,
                prompt,
                claim_set,
                semantic_feedback,
            ),
        )
        report_body = _require_l3_report_body(report_output.report_body)
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
    except L3ReportBodyEmptyError as exc:
        logger.error("[analyze_l3_dimension] %s: %s", dim_key, str(exc))
        await sse_manager.publish(session_id, {
            "type": SSEEventType.DIMENSION_ERROR,
            "dimension_key": dim_key,
            "dimension_name": dim_name,
            "layer": dim_layer,
            "error": str(exc),
        })
        return {
            "messages": [AIMessage(content=f"[执行失败] {exc}")],
            "dimension_retry_counts": dimension_failure_attempt(state, dim_key),
            "provider_failures": [{
                "stage": f"L{dim_layer}",
                "dimension": dim_key,
                "code": "l3_report_body_empty",
                "message": str(exc),
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
        from app.infrastructure.llm.structured import structured_failure_summary

        failure_summary = structured_failure_summary(exc)
        logger.error(
            "[analyze_l3_dimension] %s: structured output failed to parse (%s)",
            dim_key,
            failure_summary,
        )
        await sse_manager.publish(session_id, {
            "type": SSEEventType.DIMENSION_ERROR,
            "dimension_key": dim_key,
            "dimension_name": dim_name,
            "layer": dim_layer,
            "error": failure_summary,
        })
        return {
            "messages": [AIMessage(content=f"[执行失败] 结构化输出解析失败: {exc}")],
            "dimension_retry_counts": dimension_failure_attempt(state, dim_key),
            "provider_failures": [{
                "stage": f"L{dim_layer}", "dimension": dim_key,
                "code": "llm_provider_error",
                "message": failure_summary,
            }],
        }
    except Exception as e:
        # Genuine provider infrastructure failure (transport/HTTP/circuit).
        quota_exhausted = is_provider_quota_exhausted(e)
        if is_provider_failure(e) and not quota_exhausted:
            trip_provider_failure(session_id)
        from app.infrastructure.llm.structured import structured_failure_summary

        failure_summary = structured_failure_summary(e)
        logger.error(
            "[analyze_l3_dimension] %s: LLM provider failure (%s)",
            dim_key,
            failure_summary,
        )
        await sse_manager.publish(session_id, {
            "type": SSEEventType.DIMENSION_ERROR,
            "dimension_key": dim_key,
            "dimension_name": dim_name,
            "layer": dim_layer,
            "error": failure_summary,
        })
        return {
            "messages": [AIMessage(content=f"[执行失败] LLM错误: {e}")],
            "dimension_retry_counts": dimension_failure_attempt(state, dim_key),
            "provider_failures": [{
                "stage": f"L{dim_layer}", "dimension": dim_key,
                "code": (
                    "llm_provider_quota_exhausted"
                    if quota_exhausted
                    else "llm_provider_error"
                ),
                "message": failure_summary,
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
    llm_response = report_body
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
            "claims_with_evidence": sum(
                _claim_lineage_present(claim) for claim in claim_set.claims
            ),
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
                "claims_with_evidence": sum(
                    _claim_lineage_present(claim) for claim in claim_set.claims
                ),
            },
            diagnostics={
                "rag_sources": len(rag_log.sources) if rag_log and rag_log.rag_enabled else 0,
                "evidence_source_types": list(evidence_trace.get("source_types", [])),
                "evidence_fact_count": int(evidence_trace.get("fact_count", 0) or 0),
                "evidence_candidate_count": int(evidence_trace.get("candidate_count", 0) or 0),
                "evidence_relation_count": int(evidence_trace.get("relation_count", 0) or 0),
                "evidence_coverage_status": str(
                    evidence_trace.get("coverage_status", "") or ""
                ),
                "kg_cognition": float(
                    evidence_trace.get("kg_confidence", 0.0) or 0.0
                ) > 0,
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

    from app.domain.assessment.dimension_contracts import render_dimension_semantic_contract

    source_dimensions = _l3_source_dimensions(cfg, dim_key)
    spatial_fact_evidence = _typed_l1_fact_evidence(
        state,
        dim_key,
        source_dimensions=source_dimensions,
    )
    spatial_location_evidence = _typed_l1_fact_evidence(
        state,
        dim_key,
        location_only=True,
        source_dimensions=source_dimensions,
    )
    semantic_contract = render_dimension_semantic_contract(
        dim_key,
        3,
        upstream_source_dimensions=sorted(
            value for value in source_dimensions if value not in {"", "location", "spatial", dim_key}
        ),
    )
    return f"【dimension_key={dim_key}】\n" + get_layer3_prompt(
        dimension_key=dim_key,
        project_name=project_name,
        # L1 report is the current-state analysis background.  L1 spatial
        # facts are supplied separately for auditable spatial references.
        # The provider's structured-output request includes the full schema
        # and the detailed professional template.  Keep upstream reports
        # bounded here so the request remains inside the configured provider
        # context window; GROUND receives the complete typed artifacts later.
        analysis_report=_compact_prompt_background(l1_deps, 5200, "L1 现状分析"),
        planning_concept=_compact_prompt_background(l2_deps, 3400, "L2 规划思路"),
        constraints=constraints,
        knowledge_context=rag_context or "",
        revision_instruction=revision_instruction,
        professional_data_section=professional_data_section + explore_section,
        semantic_contract=semantic_contract,
        upstream_source_dimensions=", ".join(
            sorted(
                value
                for value in source_dimensions
                if value not in {"", "location", "spatial", dim_key}
            )
        ),
        natural_villages=resolvable_villages,
        location_evidence=(
            _compact_prompt_background(spatial_fact_evidence, 3000, "已审计 L1 spatial facts")
            + "\n\n"
            + _compact_prompt_background(
                spatial_location_evidence,
                2200,
                "已审计 L1 spatial location facts",
            )
        ),
        dimension_plans=_compact_prompt_background(same_layer_contexts, 2200, "同层规划背景"),
    )


__all__ = ["analyze_l3_dimension"]
