"""Typed, display-only summary generation.

The active path validates a dimension-specific Pydantic projection, overwrites
code-owned fields, and marks provider failure as pending.  It never promotes
summary content to planning semantics.  The private deterministic extraction
helpers below remain importable for the separately scoped RAG formatter, but
are not used by this summary path.
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

# ---------------------------------------------------------------------------
# Dimension-specific regex extraction rules
# ---------------------------------------------------------------------------
# Each L3 dimension defines (Chinese metric key → [regex patterns]).
# These Chinese keys match PlanningKG.CONSTRAINT_PATTERNS expected keys.
# Extraction is deterministic — zero LLM calls.
# ---------------------------------------------------------------------------

DIMENSION_EXTRACTION_RULES: Dict[str, Dict[str, List[str]]] = {
    "land_use_planning": {
        "建设用地规模_公顷": [
            r"建设用地.*?(\d+\.?\d*)\s*(?:公顷|ha)",
            r"建设规模.*?(\d+\.?\d*)\s*(?:公顷|ha)",
            r"村庄建设用地.*?(\d+\.?\d*)",
        ],
        "耕地保有量_公顷": [
            r"耕地保有量.*?(\d+\.?\d*)\s*(?:公顷|ha)",
            r"耕地保护.*?(\d+\.?\d*)\s*(?:公顷|ha)",
        ],
        "永久基本农田_公顷": [
            r"永久基本农田.*?(\d+\.?\d*)\s*(?:公顷|ha)",
            r"基本农田.*?(\d+\.?\d*)\s*(?:公顷|ha)",
        ],
        "生态保护红线面积": [
            r"生态保护红线.*?(\d+\.?\d*)",
            r"生态红线.*?(\d+\.?\d*)\s*(?:公顷|ha)",
        ],
        "新增建设用地_公顷": [
            r"新增建设.*?(\d+\.?\d*)\s*(?:公顷|ha)",
        ],
    },
    "ecological": {
        "生态保护红线面积": [
            r"生态保护红线.*?(\d+\.?\d*)",
            r"生态红线.*?(\d+\.?\d*)\s*(?:公顷|ha)",
        ],
        "林地保有量_公顷": [
            r"林地保有量.*?(\d+\.?\d*)\s*(?:公顷|ha)",
        ],
        "森林覆盖率_百分比": [
            r"森林覆盖率.*?(\d+\.?\d*)\s*%",
        ],
    },
    "settlement_planning": {
        "建设用地规模_公顷": [
            r"建设用地.*?(\d+\.?\d*)\s*(?:公顷|ha)",
        ],
        "规划期末人口": [
            r"规划期末.*?人口.*?(\d+)",
            r"规划人口.*?(\d+)",
        ],
        "人均建设用地": [
            r"人均建设用地.*?(\d+\.?\d*)\s*m",
        ],
    },
    "superior_planning": {
        "生态保护红线面积": [
            r"生态保护红线.*?(\d+\.?\d*)",
        ],
        "耕地保有量_公顷": [
            r"耕地保有量.*?(\d+\.?\d*)\s*(?:公顷|ha)",
            r"基本农田.*?(\d+\.?\d*)\s*(?:公顷|ha)",
        ],
        "建设用地规模_公顷": [
            r"建设用地.*?(\d+\.?\d*)\s*(?:公顷|ha)",
            r"城镇开发边界.*?(\d+\.?\d*)",
        ],
    },
}


def _extract_dimension_metrics(
    dimension_key: str,
    content: str,
) -> Dict[str, Any]:
    """Dimension-specific regex extraction — deterministic, zero LLM calls."""
    rules = DIMENSION_EXTRACTION_RULES.get(dimension_key, {})
    if not rules:
        return {}

    metrics: Dict[str, Any] = {}
    for metric_key, patterns in rules.items():
        for pattern in patterns:
            m = re.search(pattern, content)
            if m:
                val = m.group(1)
                metrics[metric_key] = float(val) if '.' in val else int(val)
                break
    return metrics


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
        text_summary=str(content)[:200],
        summary_status="pending",
    )


async def generate_structured_summary(
    dimension_key: str,
    layer: int,
    content: str,
) -> str:
    """Serialize the typed summary at the report-storage boundary only."""

    summary = await generate_summary_model(dimension_key, layer, content)
    return summary.model_dump_json(ensure_ascii=False)


def deterministic_summary_model(
    dimension_key: str,
    layer: int,
    content: str,
) -> BaseDimensionSummary:
    """Build a deterministic display projection without semantic parsing."""

    return build_derived_summary(
        dimension_key,
        layer,
        word_count=len(content or ""),
        text_summary=str(content or "")[:200],
        summary_status="deterministic",
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
- key_points: 3-5 条核心发现
- text_summary: 200 字以内自然语言概述
- metrics: 维度特定指标，无法从报告确认则留空
- 维度专属字段: 从报告中提取，无法提取则 null/空
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

    summary = _finalize_summary(
        summary,
        dimension_key,
        layer,
        content,
        summary_status="resolved",
    )
    _sync_schema_fields_to_metrics(summary)
    return _finalize_summary(
        summary,
        dimension_key,
        layer,
        content,
        summary_status="resolved",
    )


def _sync_schema_fields_to_metrics(summary: BaseDimensionSummary) -> None:
    """Copy dimension-specific schema field values into metrics dict.

    Ensures conflict_detector can find values via _get_metric_value()
    regardless of whether they came from LLM or schema defaults.
    """
    for field_name in type(summary).model_fields:
        if field_name in (
            "dimension_key", "layer", "word_count", "key_points", "text_summary",
            "metrics", "evidence_refs", "summary_source", "summary_status", "authority",
        ):
            continue
        value = getattr(summary, field_name, None)
        if value is not None and field_name not in summary.metrics:
            summary.metrics[field_name] = value


def _extract_metrics_regex(content: str) -> Dict[str, Any]:
    """Extract key numeric metrics via generic regex patterns."""
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
    """Extract key points from markdown headings and bold text."""
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
    "deterministic_summary_model",
    "generate_summary_model",
    "generate_structured_summary",
]
