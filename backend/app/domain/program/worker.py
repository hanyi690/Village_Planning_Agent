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


def _l3_report_attempt_key(
    state: Dict[str, Any],
    dimension_key: str,
) -> str:
    """Identify one checkpoint attempt without depending on its DB version."""
    payload = {
        "session_id": str(state.get("session_id") or ""),
        "dimension_key": dimension_key,
        "branch_id": str(state.get("branch_id") or "main"),
        "is_revision": bool(state.get("is_revision")),
        "revision_feedback": str(state.get("revision_feedback") or ""),
        "revision_target_dimensions": sorted(
            str(value).strip()
            for value in (state.get("revision_target_dimensions") or [])
            if str(value).strip()
        ),
        "revision_impact_tree": state.get("revision_impact_tree") or {},
        "human_review_generation": int(state.get("human_review_generation") or 0),
    }
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _stable_report_id(
    session_id: str,
    dimension_key: str,
    logical_attempt: Any,
) -> str:
    """Return the idempotency key for one logical report attempt."""
    payload = json.dumps(
        {
            "session_id": session_id,
            "dimension_key": dimension_key,
            "logical_attempt": logical_attempt,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return "report:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


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


def _projection_cache_key(
    *,
    prompt: str,
    validation_feedback: list[str] | None,
    response_model: Any,
    cache_contract: str,
    schema_context: Any = None,
) -> str:
    return json.dumps(
        {
            "prompt": prompt,
            "validation_feedback": validation_feedback or [],
            "schema_checksum": hashlib.sha256(
                json.dumps(
                    response_model.model_json_schema(),
                    ensure_ascii=False,
                    sort_keys=True,
                ).encode("utf-8")
            ).hexdigest(),
            "cache_contract": cache_contract,
            "schema_context": schema_context,
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def _l3_claim_schema(
    source_fact_ids: Iterable[str],
    spatial_source_fact_ids: Iterable[str],
) -> tuple[Any, tuple[str, ...], tuple[str, ...]]:
    """Return the exact claims schema and normalized IDs for one invocation."""

    normalized_source_ids = tuple(
        sorted({str(item).strip() for item in source_fact_ids if str(item).strip()})
    )
    normalized_spatial_ids = tuple(
        sorted({str(item).strip() for item in spatial_source_fact_ids if str(item).strip()})
    )
    from app.infrastructure.llm.planning_claims import _dynamic_claim_output_model

    response_model = _dynamic_claim_output_model(
        normalized_source_ids,
        normalized_spatial_ids,
    )
    return (
        response_model,
        normalized_source_ids,
        normalized_spatial_ids,
    )


def _validate_l3_projection(response_model: Any, generated: Any) -> Any:
    """Validate injected and cached values against the same response model."""

    if generated is None:
        raise ValueError("L3 structured provider returned no typed projection")
    if isinstance(generated, response_model):
        return generated
    payload = (
        generated.model_dump(mode="python")
        if hasattr(generated, "model_dump")
        else generated
    )
    return response_model.model_validate(payload)


def _write_projection_cache(path: Path, generated: Any) -> None:
    """Persist only a caller-validated projection; cache I/O is best effort."""

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(f".{uuid.uuid4().hex}.tmp")
        temporary.write_text(generated.model_dump_json(indent=2), encoding="utf-8")
        os.replace(temporary, path)
    except (OSError, TypeError, ValueError) as exc:
        logger.warning("[analyze_l3_dimension] projection cache write skipped %s: %s", path, exc)


async def _cached_claim_only_generation(
    generator: Any,
    *,
    session_id: str,
    dimension_key: str,
    prompt: str,
    validation_feedback: list[str] | None = None,
    source_fact_ids: Iterable[str] = (),
    spatial_source_fact_ids: Iterable[str] = (),
):
    """Generate or resume the claims-only L3 projection."""

    response_model, normalized_source_ids, normalized_spatial_ids = _l3_claim_schema(
        source_fact_ids,
        spatial_source_fact_ids,
    )

    cache_key = _projection_cache_key(
        prompt=prompt,
        validation_feedback=validation_feedback,
        response_model=response_model,
        cache_contract="l3-claims-only-v2",
        schema_context={
            "source_fact_ids": list(normalized_source_ids),
            "spatial_source_fact_ids": list(normalized_spatial_ids),
        },
    )
    path = _projection_cache_path(session_id, dimension_key, cache_key, "claims")
    if path.exists():
        try:
            return response_model.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            logger.warning("[analyze_l3_dimension] ignoring invalid claims cache %s", path)
    generate_claims = getattr(generator, "generate_claims", None)
    if not callable(generate_claims):
        raise TypeError("L3 claims generator must expose generate_claims()")
    generation_kwargs: dict[str, Any] = {
        "validation_feedback": validation_feedback,
    }
    generation_kwargs.update({
        "source_fact_ids": normalized_source_ids,
        "spatial_source_fact_ids": normalized_spatial_ids,
    })
    generated = await generate_claims(prompt, **generation_kwargs)
    return _validate_l3_projection(response_model, generated)


async def _cached_report_generation(
    generator: Any,
    *,
    session_id: str,
    dimension_key: str,
    prompt: str,
):
    """Generate or resume the report-only L3 projection."""

    from app.domain.program.claim_draft import L3ReportOutput

    cache_key = _projection_cache_key(
        prompt=prompt,
        validation_feedback=None,
        response_model=L3ReportOutput,
        cache_contract="l3-report-only-v2",
    )
    path = _projection_cache_path(session_id, dimension_key, cache_key, "report")
    if path.exists():
        try:
            cached = L3ReportOutput.model_validate_json(
                path.read_text(encoding="utf-8")
            )
            _require_l3_report_body(cached.report_body)
            return cached
        except (OSError, ValueError) as exc:
            logger.warning(
                "[analyze_l3_dimension] ignoring invalid or empty report cache %s: %s",
                path,
                exc,
            )
    generate_report = getattr(generator, "generate_report", None)
    if not callable(generate_report):
        raise TypeError("L3 report generator must expose generate_report()")
    generated = await generate_report(prompt)
    return _validate_l3_projection(L3ReportOutput, generated)


def _persist_validated_claims(
    *,
    session_id: str,
    dimension_key: str,
    prompt: str,
    generated: Any,
    source_fact_ids: Iterable[str] = (),
    spatial_source_fact_ids: Iterable[str] = (),
) -> None:
    response_model, normalized_source_ids, normalized_spatial_ids = _l3_claim_schema(
        source_fact_ids,
        spatial_source_fact_ids,
    )

    cache_key = _projection_cache_key(
        prompt=prompt,
        validation_feedback=None,
        response_model=response_model,
        cache_contract="l3-claims-only-v2",
        schema_context={
            "source_fact_ids": list(normalized_source_ids),
            "spatial_source_fact_ids": list(normalized_spatial_ids),
        },
    )
    _write_projection_cache(
        _projection_cache_path(session_id, dimension_key, cache_key, "claims"),
        generated,
    )


def _persist_validated_report(
    *,
    session_id: str,
    dimension_key: str,
    prompt: str,
    generated: Any,
) -> None:
    from app.domain.program.claim_draft import L3ReportOutput

    cache_key = _projection_cache_key(
        prompt=prompt,
        validation_feedback=None,
        response_model=L3ReportOutput,
        cache_contract="l3-report-only-v2",
    )
    _write_projection_cache(
        _projection_cache_path(session_id, dimension_key, cache_key, "report"),
        generated,
    )

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


def _fact_value(fact: Any, name: str, default: Any = "") -> Any:
    if isinstance(fact, dict):
        return fact.get(name, default)
    return getattr(fact, name, default)


def _l3_snapshot_data(
    state: Dict[str, Any],
) -> tuple[list[Any], list[Any]]:
    """Load the L1 facts and location facts for one exact snapshot version."""

    artifact_ref = ((state or {}).get("artifact_refs") or {}).get("l1_snapshot")
    if artifact_ref:
        try:
            from app.infrastructure.artifacts.runtime import load_artifact
            from app.contracts.domain.l1_contracts import L1Snapshot

            payload = load_artifact(state, "l1_snapshot")
            if payload is None:
                return [], []
            snapshot = (
                payload
                if isinstance(payload, L1Snapshot)
                else L1Snapshot.model_validate(
                    payload.model_dump(mode="json")
                    if hasattr(payload, "model_dump")
                    else payload,
                    strict=False,
                )
            )
            return (
                list(snapshot.fact_records or []),
                list(snapshot.location_facts or []),
            )
        except Exception:
            # An explicit but unreadable snapshot must not fall back to a
            # different cached context version.
            return [], []

    try:
        from app.infrastructure.context.planning_context_factory import get_cached_context

        context = get_cached_context(str(state.get("session_id", "")))
        if context is None:
            return [], []
        return (
            list(getattr(context, "l1_fact_records", []) or []),
            list(getattr(context, "location_facts", []) or []),
        )
    except Exception:
        return [], []


def _l3_fact_catalog(
    state: Dict[str, Any],
    dimension_key: str,
    source_dimensions: Iterable[str],
):
    """Build the one bounded L1 fact catalog shared by prompt and validator."""

    from app.domain.program.claim_compiler import source_fact_options
    from app.domain.validation.l1_fact_catalog import (
        build_l1_fact_catalog,
        empty_l1_fact_catalog,
    )

    try:
        facts, _location_facts = _l3_snapshot_data(state)
        options = source_fact_options(
            dimension_key,
            "fact",
            facts,
            source_dimensions=source_dimensions,
        )[:48]
        allowed_ids = {item.ref_id for item in options}
        return build_l1_fact_catalog(
            fact
            for fact in facts
            if str(_fact_value(fact, "fact_id", "") or "").strip() in allowed_ids
        )
    except Exception:
        return empty_l1_fact_catalog()


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
    from app.domain.validation.l1_fact_catalog import SPATIAL_L1_FACT_KINDS

    facts, location_facts = _l3_snapshot_data(state)
    if not facts and not location_facts:
        return "（当前上下文没有可用的 L1 spatial evidence；不得据此创建空间 claim。）"

    source_dimension_values = tuple(
        source_dimensions or (dimension_key, "location", "spatial", "")
    )
    allowed_dimensions = {
        str(value).strip()
        for value in source_dimension_values
        if str(value).strip() or value == ""
    }
    if location_only:
        rows: list[dict[str, Any]] = []
        for item in location_facts:
            fact_dimension = str(_fact_value(item, "dimension_key", "") or "").strip()
            if fact_dimension not in allowed_dimensions:
                continue
            mention = str(_fact_value(item, "mention", "") or "").strip()
            normalized_name = str(_fact_value(item, "normalized_name", "") or "").strip()
            if not mention and not normalized_name:
                continue
            rows.append({
                "mention": mention,
                "normalized_name": normalized_name,
                "role": str(_fact_value(item, "role", "") or ""),
                "dimension_key": fact_dimension,
                "spatial_hint": str(_fact_value(item, "spatial_hint", "") or ""),
                "related_mentions": list(_fact_value(item, "related_mentions", []) or []),
                "evidence_refs": list(_fact_value(item, "evidence_refs", []) or []),
                "source_report_ref": str(_fact_value(item, "source_report_ref", "") or ""),
            })
            if len(rows) >= 24:
                break
        if not rows:
            return "（当前 L1 没有带证据引用的 L1 spatial location facts；不得从地点名单推断对象位置。）"
        return "【已审计 L1 spatial location facts】\n" + json.dumps(
            rows, ensure_ascii=False, indent=2
        )

    catalog = _l3_fact_catalog(state, dimension_key, source_dimension_values)
    fact_by_id = {
        str(_fact_value(fact, "fact_id", "") or "").strip(): fact
        for fact in facts
    }
    allowed_fact_ids = set(catalog.usable_allowed_fact_ids)
    rows = []
    usable_candidates = list(catalog.candidates) if catalog.is_unambiguous else []
    for candidate in usable_candidates:
        fact = fact_by_id.get(candidate.candidate_id)
        metadata = candidate.metadata or {}
        rows.append({
            "fact_id": candidate.candidate_id,
            "statement": candidate.label[:360],
            "fact_kind": str(metadata.get("fact_kind") or candidate.kind),
            "dimension_key": str(metadata.get("dimension_key") or ""),
            "semantic_type": str(_fact_value(fact, "semantic_type", "") or ""),
            "subject_scope": str(_fact_value(fact, "subject_scope", "") or ""),
            "attributes": _bounded_prompt_attributes(
                _fact_value(fact, "attributes", {}) if fact is not None else {}
            ),
            "source_refs": [
                str(ref).strip()
                for ref in (_fact_value(fact, "source_refs", []) if fact is not None else [])
                if str(ref).strip()
                and not (
                    str(ref).strip().startswith("l1:fact:")
                    and str(ref).strip() not in allowed_fact_ids
                )
            ],
            "source_feature_ids": list(
                _fact_value(fact, "source_feature_ids", []) if fact is not None else []
            ),
            "source_snapshot_ref": str(
                _fact_value(fact, "source_snapshot_ref", "") if fact is not None else ""
            ),
        })
    if not rows:
        return "（当前上下文没有可用的 L1 typed facts；不得据此创建空间 claim。）"
    return (
        "【已审计 L1 planning facts】\n"
        "这些记录是当前 L1 快照的权威结构化事实。非空间 claim 可引用对应 fact_id；"
        "空间 claim 的 source_fact_refs 只能逐字引用当前候选中的空间 fact_kind 记录；"
        "source_feature_ids 只用于说明可由后续 EvidenceGraph 继续连接，不能在 L3 直接当作几何。\n"
        + json.dumps(rows, ensure_ascii=False, indent=2)
    )


def _l3_candidate_context(
    state: Dict[str, Any],
    dimension_key: str,
    source_dimensions: Iterable[str],
) -> str:
    """Render the small, current candidate space used by the claims pass."""

    source_dimension_values = tuple(source_dimensions)
    try:
        from app.domain.validation.l1_fact_catalog import SPATIAL_L1_FACT_KINDS
        from app.domain.program.target_projection.relation_catalog import relation_options

        catalog = _l3_fact_catalog(state, dimension_key, source_dimension_values)
        usable_candidates = (
            list(catalog.candidates) if catalog.is_unambiguous else []
        )
        source_options = [item.candidate_id for item in usable_candidates]
        spatial_source_options = [
            item.candidate_id
            for item in usable_candidates
            if item.metadata.get("fact_kind") in SPATIAL_L1_FACT_KINDS
        ]
        relation_candidates = {
            kind: [item.template for item in relation_options(kind)]
            for kind in ("facility", "road", "linear", "axis", "site_area", "zone")
        }
        spatial_ids = set(spatial_source_options)
        source_catalog = [
            {
                "fact_id": item.candidate_id,
                "fact_kind": item.metadata.get("fact_kind", item.kind),
                "label": item.label,
                "spatial_claim_allowed": item.candidate_id in spatial_ids,
            }
            for item in usable_candidates
        ]
        payload = {
            "source_fact_options": source_options,
            "spatial_source_fact_options": spatial_source_options,
            "source_fact_catalog": source_catalog,
            "source_fact_catalog_digest": catalog.digest,
            "source_fact_catalog_status": (
                "usable" if catalog.is_unambiguous else "ambiguous"
            ),
            "relation_options_by_subject_kind": relation_candidates,
            "source_dimensions": sorted(
                str(item) for item in source_dimension_values if str(item).strip()
            ),
        }
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)
    except Exception:
        return json.dumps({
            "source_fact_options": [],
            "spatial_source_fact_options": [],
            "source_fact_catalog": [],
            "source_fact_catalog_digest": "",
            "source_fact_catalog_status": "unavailable",
            "relation_options_by_subject_kind": {},
            "source_dimensions": sorted(
                str(item) for item in source_dimension_values if str(item).strip()
            ),
        }, ensure_ascii=False, sort_keys=True)


def _spatial_claim_evidence_errors(
    state: Dict[str, Any],
    claim_set: PlanningClaimSet,
    *,
    source_dimensions: Iterable[str] | None = None,
) -> list[str]:
    """Return exact closed-set violations for emitted L1 fact identities.

    This is an exact identity check, not a name/regex matcher. A spatial claim
    without source_fact_refs is a valid semantic candidate and must continue
    to GROUND, where EvidenceGraph resolves its location. If the model does
    provide source_fact_refs, every id must exist in the bounded candidate set
    rendered in the prompt. Spatial claims may only cite the spatial subset.
    This function never rewrites an emitted id.
    """
    spatial_kinds = {"parcel", "polygon", "point", "line"}
    claims = list(getattr(claim_set, "claims", []) or [])
    if not claims:
        return []
    try:
        catalog = _l3_fact_catalog(
            state,
            str(getattr(claim_set, "dimension_key", "") or "").strip(),
            source_dimensions or (),
        )
    except Exception:
        from app.domain.validation.l1_fact_catalog import empty_l1_fact_catalog

        catalog = empty_l1_fact_catalog()
    spatial_fact_ids = set(catalog.usable_spatial_fact_ids)
    errors: list[str] = []
    for claim in claims:
        claim_id = str(getattr(claim, "claim_id", "") or "claim")
        refs = [
            str(ref).strip()
            for ref in (getattr(claim, "source_fact_refs", []) or [])
            if str(ref).strip()
        ]
        if not refs:
            continue
        from app.domain.validation.l1_fact_catalog import validate_l1_fact_references

        membership = validate_l1_fact_references(refs, catalog=catalog)
        unknown = sorted(set(membership.extra_ids))
        if unknown:
            errors.append(
                f"ERROR[claim_unknown_source_fact] {claim_id}: "
                f"source_fact_refs are not in the current L1 candidate set: {unknown}"
            )
        if membership.duplicate_ids:
            errors.append(
                f"ERROR[claim_duplicate_source_fact] {claim_id}: "
                f"source_fact_refs contain duplicates: {list(membership.duplicate_ids)}"
            )
        if getattr(claim, "suggested_output_kind", "") in spatial_kinds:
            known_fact_ids = set(catalog.usable_allowed_fact_ids)
            non_spatial = sorted((set(refs) & known_fact_ids) - spatial_fact_ids)
            if non_spatial:
                errors.append(
                    f"ERROR[spatial_claim_non_spatial_fact] {claim_id}: "
                    f"spatial claims may cite only spatial L1 candidates: {non_spatial}"
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


def _normalize_claim_components(
    *,
    dimension_key: str,
    output: Any,
) -> tuple[Any, PlanningClaimSet]:
    """Convert validated provider components once into the strict claim contract."""

    from app.domain.program.claim_draft import (
        PlanningClaimDraftSet,
        component_to_planning_claim_draft,
        normalize_claim_draft_set,
    )

    draft_set = PlanningClaimDraftSet(
        dimension_key=dimension_key,
        claims=[
            component_to_planning_claim_draft(item, dimension_key=dimension_key)
            for item in output.claims
        ],
    )
    claim_set = normalize_claim_draft_set(draft_set, dimension_key=dimension_key)
    if draft_set.claims and not claim_set.claims:
        raise ValueError(
            "L3 claim projection quarantined every emitted component; "
            "no executable or pending claim remains"
        )
    return draft_set, claim_set


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
    from app.infrastructure.llm import get_planning_claim_generator

    claim_generator = get_planning_claim_generator()
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

    source_dimensions = _l3_source_dimensions(cfg, dim_key)
    fact_catalog = _l3_fact_catalog(state, dim_key, source_dimensions)
    source_fact_ids = tuple(
        fact_catalog.usable_allowed_fact_ids
        if fact_catalog.is_unambiguous
        else ()
    )
    spatial_source_fact_ids = tuple(
        fact_catalog.usable_spatial_fact_ids
        if fact_catalog.is_unambiguous
        else ()
    )
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
            source_fact_ids=source_fact_ids,
            spatial_source_fact_ids=spatial_source_fact_ids,
        )
        draft_set, claim_set = _normalize_claim_components(
            dimension_key=dim_key,
            output=output,
        )
        semantic_feedback = _spatial_claim_evidence_errors(
            state,
            claim_set,
            source_dimensions=_l3_source_dimensions(cfg, dim_key),
        )
        if semantic_feedback:
            output = await _cached_claim_only_generation(
                claim_generator,
                session_id=session_id,
                dimension_key=dim_key,
                prompt=prompt,
                validation_feedback=semantic_feedback,
                source_fact_ids=source_fact_ids,
                spatial_source_fact_ids=spatial_source_fact_ids,
            )
            draft_set, claim_set = _normalize_claim_components(
                dimension_key=dim_key,
                output=output,
            )
            semantic_feedback = _spatial_claim_evidence_errors(
                state,
                claim_set,
                source_dimensions=_l3_source_dimensions(cfg, dim_key),
            )
            if semantic_feedback:
                raise ValueError(
                    "L3_SOURCE_FACT_CLOSED_SET_FAILED: "
                    + "; ".join(semantic_feedback[:20])
                )
        if claim_set is None:
            raise ValueError("L3 claim projection returned no validated claim set")
        _persist_validated_claims(
            session_id=session_id,
            dimension_key=dim_key,
            prompt=prompt,
            generated=output,
            source_fact_ids=source_fact_ids,
            spatial_source_fact_ids=spatial_source_fact_ids,
        )
        report_prompt = _build_l3_report_synthesis_prompt(
            dim_key,
            prompt,
            claim_set,
            semantic_feedback,
        )
        report_output = await _cached_report_generation(
            claim_generator,
            session_id=session_id,
            dimension_key=dim_key,
            prompt=report_prompt,
        )
        report_body = _require_l3_report_body(report_output.report_body)
        _persist_validated_report(
            session_id=session_id,
            dimension_key=dim_key,
            prompt=report_prompt,
            generated=report_output,
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
            "dimension_failures": [{
                "stage": f"L{dim_layer}",
                "dimension": dim_key,
                "code": "dimension_quality_failed",
                "message": str(exc),
                "feedback": (
                    "L3 report synthesis returned an empty report_body after the claims "
                    "passed validation. Regenerate only the human-readable report_body from "
                    "the validated claims; do not change claims, IDs, locations, geometry, "
                    "quantities or source facts."
                ),
            }],
        }
    except (ValueError, TypeError) as exc:
        # L3 content/schema/closed-set failures are dimension quality failures,
        # not provider infrastructure failures.  They must not trip the session
        # circuit or trigger a broad provider resume for unrelated dimensions.
        from app.infrastructure.llm.structured import structured_failure_summary

        failure_summary = structured_failure_summary(exc)
        logger.error(
            "[analyze_l3_dimension] %s: structured output/quality validation failed (%s)",
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
            "dimension_failures": [{
                "stage": f"L{dim_layer}", "dimension": dim_key,
                "code": "dimension_quality_failed",
                "message": failure_summary,
                "feedback": (
                    "L3 structured claims did not pass the current schema or closed-set "
                    "boundary. Retry only this dimension with the same dynamic candidate "
                    "catalog; copy source_fact_refs exactly from the current candidate set, "
                    "keep each list unique, and leave the list empty when no cited fact is "
                    "available. Do not use EXPLORE lineage, report, bundle, place, BSM or "
                    "geometry IDs as fact IDs. "
                    + failure_summary
                )[:4000],
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
    llm_elapsed = time.time() - llm_start_time
    logger.info(f"[analyze_l3_dimension] {dim_key}: LLM completed in {llm_elapsed:.1f}s, output = {len(llm_response)} chars")

    # 6.5 统计收集 - 记录 LLM 时间和输出
    stats.record_llm_time(session_id, dim_key, llm_elapsed, len(llm_response))
    stats.end_dimension(session_id, dim_key)

    # 7. 准备报告数据（累积到 pending_reports，由 completion.py 批量写入）
    store = ReportStore.get_instance()
    report_id = _stable_report_id(
        session_id,
        dim_key,
        _l3_report_attempt_key(state, dim_key),
    )
    try:
        existing_report = await store.get_report(report_id)
        if (
            existing_report is not None
            and existing_report.session_id == session_id
            and existing_report.dimension_key == dim_key
        ):
            next_version = int(existing_report.version)
        else:
            latest_version = await store.get_latest_version(session_id, dim_key)
            next_version = latest_version + 1
    except Exception as exc:  # noqa: BLE001 - persist failure must be explicit
        message = (
            "L3 report persistence unavailable while recovering or allocating the next version: "
            f"{type(exc).__name__}"
        )
        logger.error("[analyze_l3_dimension] %s: %s", dim_key, message)
        await sse_manager.publish(session_id, {
            "type": SSEEventType.DIMENSION_ERROR,
            "dimension_key": dim_key,
            "dimension_name": dim_name,
            "layer": dim_layer,
            "error": message,
        })
        return {
            "messages": [AIMessage(content=f"[执行失败] {message}")],
            "dimension_retry_counts": dimension_failure_attempt(state, dim_key),
            "dimension_failures": [{
                "stage": f"L{dim_layer}",
                "dimension": dim_key,
                "code": "report_persistence_failed",
                "message": message,
            }],
        }
    revision_reason = state.get("revision_feedback") or state.get("feedback")

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

    # Persist before any completion event or completed-dimension marker.  A
    # report that is only in memory must never make the layer appear complete.
    if not await save_report_immediate(store, pending_report):
        message = "L3 report persistence failed; the dimension remains incomplete"
        logger.error("[analyze_l3_dimension] %s: %s", dim_key, message)
        await sse_manager.publish(session_id, {
            "type": SSEEventType.DIMENSION_ERROR,
            "dimension_key": dim_key,
            "dimension_name": dim_name,
            "layer": dim_layer,
            "error": message,
        })
        return {
            "messages": [AIMessage(content=f"[执行失败] {message}")],
            "dimension_retry_counts": dimension_failure_attempt(state, dim_key),
            "pending_reports": [pending_report],
            "dimension_failures": [{
                "stage": f"L{dim_layer}",
                "dimension": dim_key,
                "code": "report_persistence_failed",
                "message": message,
            }],
        }

    await publish_dimension_delta(
        session_id,
        dim_key,
        dim_name,
        dim_layer,
        is_revision,
        llm_response,
        llm_response,
    )

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
    candidate_context = _l3_candidate_context(
        state,
        dim_key,
        source_dimensions,
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
        location_evidence=(
            _compact_prompt_background(spatial_fact_evidence, 3000, "已审计 L1 spatial facts")
            + "\n\n"
            + _compact_prompt_background(
                spatial_location_evidence,
                2200,
                "已审计 L1 spatial location facts",
            )
        ),
        candidate_context=candidate_context,
        dimension_plans=_compact_prompt_background(same_layer_contexts, 2200, "同层规划背景"),
    )


__all__ = ["analyze_l3_dimension"]
