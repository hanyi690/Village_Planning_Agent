"""Typed, display-only summary generation.

The active path validates a dimension-specific Pydantic projection, overwrites
code-owned fields, and marks provider failure as pending.  It never promotes
summary content to planning semantics.  The two private regex helpers at the
bottom are retained only for the RAG query-context formatter; their output is
not a summary model and never becomes authoritative planning input.
"""

from __future__ import annotations

import asyncio
import re
from functools import lru_cache
from typing import Any, Dict, List, Literal, Optional

from app.infrastructure.logging import get_logger
from pydantic import ConfigDict, Field, create_model
from .schemas import (
    BaseDimensionSummary,
    get_dimension_schema,
    get_metrics_description,
)

logger = get_logger(__name__)

SUMMARY_AUTHORITY = "derived_summary"


@lru_cache(maxsize=None)
def derived_summary_schema(dimension_key: str) -> type[BaseDimensionSummary]:
    """Build the strict, display-only summary model for one dimension.

    The provider schema is still selected per dimension, but the authority
    marker is owned by this code path.  ``extra='forbid'`` is applied both in
    the model config and at each validation boundary so provider-only fields
    cannot silently become summary data.
    """

    dimension_schema = get_dimension_schema(dimension_key)
    return create_model(
        f"{dimension_schema.__name__}DerivedSummary",
        __base__=dimension_schema,
        __config__=ConfigDict(extra="forbid"),
        authority=(
            Literal[SUMMARY_AUTHORITY],
            Field(default=SUMMARY_AUTHORITY, frozen=True),
        ),
    )


def build_derived_summary(
    dimension_key: str,
    layer: int,
    *,
    word_count: int,
    key_points: Optional[List[str]] = None,
    text_summary: str = "",
    metrics: Optional[Dict[str, Any]] = None,
    evidence_refs: Optional[List[str]] = None,
    summary_status: str = "resolved",
) -> BaseDimensionSummary:
    """Create a display projection from already accepted typed data.

    This helper intentionally has no report parser and no planning output
    fields.  Callers supply only accepted, already-typed values; deterministic
    identity/status fields are overwritten here before strict validation.
    """

    payload: Dict[str, Any] = {
        "dimension_key": dimension_key,
        "layer": layer,
        "word_count": max(0, int(word_count)),
        "key_points": list(key_points or [])[:5],
        "text_summary": str(text_summary or "")[:200],
        "metrics": dict(metrics or {}),
        "evidence_refs": list(dict.fromkeys(str(ref) for ref in (evidence_refs or []) if str(ref).strip())),
        "summary_source": SUMMARY_AUTHORITY,
        "summary_status": summary_status,
        "authority": SUMMARY_AUTHORITY,
    }
    return derived_summary_schema(dimension_key).model_validate(payload, extra="forbid")


def _finalize_summary(
    summary: BaseDimensionSummary,
    dimension_key: str,
    layer: int,
    content: str,
    *,
    summary_status: str,
) -> BaseDimensionSummary:
    """Apply code-owned fields and revalidate the complete typed projection."""

    payload = summary.model_dump(mode="python")
    merged_metrics = dict(payload.get("metrics") or {})
    payload.update(
        {
            "dimension_key": dimension_key,
            "layer": layer,
            "word_count": len(content or ""),
            "key_points": list(payload.get("key_points") or [])[:5],
            "text_summary": str(payload.get("text_summary") or "")[:200],
            "metrics": merged_metrics,
            "summary_source": SUMMARY_AUTHORITY,
            "summary_status": summary_status,
            "authority": SUMMARY_AUTHORITY,
        }
    )
    return derived_summary_schema(dimension_key).model_validate(payload, extra="forbid")


async def generate_summary_model(
    dimension_key: str,
    layer: int,
    content: str,
) -> BaseDimensionSummary:
    """Generate a strict, display-only summary object.

    The LLM may propose only fields from the dimension schema.  On provider
    failure the result is explicitly pending and contains no guessed metrics,
    key points, entities, or planning semantics.
    """

    from app.core.settings import BACKGROUND_SUMMARY_ENRICHMENT

    if not BACKGROUND_SUMMARY_ENRICHMENT or not content:
        return build_derived_summary(
            dimension_key,
            layer,
            word_count=len(content or ""),
            text_summary="" if not content else str(content)[:200],
            summary_status="resolved" if not content else "deterministic",
        )

    try:
        result = await _instructor_generate(dimension_key, layer, content)
        if result is not None:
            return result
    except Exception as exc:
        logger.warning("[summary] Instructor failed for %s: %s", dimension_key, exc)

    return build_derived_summary(
        dimension_key,
        layer,
        word_count=len(content),
        text_summary="",
        summary_status="pending",
    )


async def _instructor_generate(
    dimension_key: str,
    layer: int,
    content: str,
) -> Optional[BaseDimensionSummary]:
    """Use the dimension-specific strict schema and return the typed object."""
    from app.infrastructure.llm.instructor_client import get_instructor_client, get_structured_model

    dim_schema = derived_summary_schema(dimension_key)
    client = get_instructor_client()
    model = get_structured_model()

    metrics_desc = get_metrics_description(dimension_key)
    metrics_hint = "\n".join(f"  - {k}: {v}" for k, v in metrics_desc.items())

    prompt = f"""分析以下规划报告，提取仅用于展示的结构化摘要。

维度: {dimension_key} (Layer {layer})
报告字数: {len(content)}

可提取的维度字段:
{metrics_hint}

要求:
- key_points: 最多 5 条核心发现，可以少于 3 条；禁止为了凑数编造或改写报告没有明确支持的内容
- text_summary: 200 字以内自然语言概述
- metrics: 维度特定指标，无法从报告确认则留空
- 维度专属字段: 从报告中提取，无法提取则 null/空
- 只使用报告原文明确支持的信息；不确定、未出现或无法确认的内容必须留空/null，不得补默认值或推断
- authority、dimension_key、layer、word_count、summary_source、summary_status 由代码校验并覆盖

报告内容（前3000字）:
{content[:3000]}"""

    try:
        summary = await asyncio.to_thread(
            client.chat.completions.create,
            model=model,
            max_tokens=800,
            temperature=0.1,
            max_retries=2,
            response_model=dim_schema,
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception as e:
        logger.warning(f"[summary] Instructor call failed for {dimension_key}: {e}")
        return None

    if not isinstance(summary, BaseDimensionSummary):
        return None

    _sync_schema_fields_to_metrics(
        summary,
        fields_set=set(getattr(summary, "model_fields_set", set())),
    )
    return _finalize_summary(
        summary,
        dimension_key,
        layer,
        content,
        summary_status="resolved",
    )


def _sync_schema_fields_to_metrics(
    summary: BaseDimensionSummary,
    *,
    fields_set: set[str] | None = None,
) -> None:
    """Copy explicitly returned dimension fields into ``metrics``.

    ``model_fields_set`` is important here: Pydantic materializes optional and
    list defaults during validation, but those defaults are not observations
    and must not be projected as semantic metrics.
    """
    provided_fields = (
        set(fields_set)
        if fields_set is not None
        else set(getattr(summary, "model_fields_set", set()))
    )
    for field_name in type(summary).model_fields:
        if field_name in (
            "dimension_key", "layer", "word_count", "key_points", "text_summary",
            "metrics", "evidence_refs", "summary_source", "summary_status", "authority",
        ):
            continue
        if field_name not in provided_fields:
            continue
        value = getattr(summary, field_name, None)
        if value is not None and field_name not in summary.metrics:
            summary.metrics[field_name] = value


def _extract_metrics_regex(content: str) -> Dict[str, Any]:
    """Build a RAG-only context supplement; never build a summary model."""
    metrics: Dict[str, Any] = {}

    patterns = [
        (r'([\d.]+)\s*公顷', 'area_ha'),
        (r'([\d.]+)\s*亩', 'area_mu'),
        (r'(\d+)\s*人', 'population'),
        (r'(\d+)\s*户', 'households'),
        (r'([\d.]+)\s*%', 'percentage'),
        (r'([\d.]+)\s*万元', 'amount_wan_yuan'),
        (r'([\d.]+)\s*km', 'length_km'),
        (r'([\d.]+)\s*m[²2]', 'area_sqm'),
    ]

    for pat, key in patterns:
        m = re.search(pat, content)
        if m:
            val = m.group(1)
            metrics[key] = float(val) if '.' in val else int(val)

    return metrics


def _extract_key_points_regex(content: str) -> List[str]:
    """Build a RAG-only heading supplement; never build a summary model."""
    points = []

    # From ### headings
    for m in re.finditer(r'###\s+(.+)', content):
        text = m.group(1).strip()
        if 4 <= len(text) <= 50:
            points.append(text)

    # From **bold** text
    for m in re.finditer(r'\*\*(.+?)\*\*', content):
        text = m.group(1).strip()
        if 4 <= len(text) <= 50 and text not in points:
            points.append(text)

    return points[:5]


__all__ = [
    "SUMMARY_AUTHORITY",
    "build_derived_summary",
    "derived_summary_schema",
    "generate_summary_model",
]
