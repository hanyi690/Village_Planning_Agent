"""Structured display summary generator using Instructor + bounded extraction.

Three-layer pipeline:
  Layer 1: Deterministic regex extraction (zero LLM)
  Layer 2: Instructor schema-enforced generation (Flash LLM, auto-retry)
  Layer 3: Fallback to regex-only on Instructor failure or empty content

The result is a display summary.  It is not an authoritative planning
contract and never renames old field spellings into current semantics.
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any, Dict, List, Optional

from app.infrastructure.logging import get_logger
from .schemas import (
    BaseDimensionSummary,
    get_dimension_schema,
    get_metrics_description,
)

logger = get_logger(__name__)

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


async def generate_structured_summary(
    dimension_key: str,
    layer: int,
    content: str,
) -> str:
    """Generate structured JSON summary for a dimension report.

    Three-layer pipeline:
      Layer 1: Deterministic regex extraction (zero LLM)
      Layer 2: Instructor schema-enforced generation (auto-retry)
      Layer 3: Fallback to regex-only on Instructor failure

    Returns JSON string compatible with the dimension's Pydantic schema.
    """
    # This is the hard boundary for the optional enrichment path.  Callers
    # outside dimension_runtime/report_store also reach this function (notably
    # background enrichment), so checking the setting only at those call sites
    # still allowed Instructor requests when enrichment was disabled.
    from app.core.settings import BACKGROUND_SUMMARY_ENRICHMENT
    if not BACKGROUND_SUMMARY_ENRICHMENT:
        return _deterministic_summary_json(dimension_key, layer, content)

    if not content:
        return _default_summary_json(dimension_key, layer)

    # Layer 1: Deterministic rule extraction
    regex_metrics = _extract_metrics_regex(content)
    dimension_metrics = _extract_dimension_metrics(dimension_key, content)
    seed_metrics = {**regex_metrics, **dimension_metrics}  # dimension-specific wins
    regex_key_points = _extract_key_points_regex(content)

    # Layer 2: Instructor schema-enforced generation
    try:
        result = await _instructor_generate(
            dimension_key, layer, content, seed_metrics
        )
        if result:
            return result
    except Exception as e:
        logger.warning(f"[summary] Instructor failed for {dimension_key}: {e}")

    # Layer 3 fallback: regex-only structured summary
    summary = BaseDimensionSummary(
        dimension_key=dimension_key,
        layer=layer,
        word_count=len(content),
        key_points=regex_key_points[:5],
        text_summary=content[:200],
        metrics=seed_metrics,
    )
    return summary.model_dump_json(ensure_ascii=False)


def _deterministic_summary_json(
    dimension_key: str,
    layer: int,
    content: str,
) -> str:
    """Return the validated summary without creating an LLM client."""
    if not content:
        return _default_summary_json(dimension_key, layer)
    regex_metrics = _extract_metrics_regex(content)
    dimension_metrics = _extract_dimension_metrics(dimension_key, content)
    summary = BaseDimensionSummary(
        dimension_key=dimension_key,
        layer=layer,
        word_count=len(content),
        key_points=_extract_key_points_regex(content)[:5],
        text_summary=content[:200],
        metrics={**regex_metrics, **dimension_metrics},
    )
    return summary.model_dump_json(ensure_ascii=False)


async def _instructor_generate(
    dimension_key: str,
    layer: int,
    content: str,
    seed_metrics: Dict[str, Any],
) -> Optional[str]:
    """Use Instructor for schema-enforced generation with auto-retry.

    Returns JSON string of dimension-specific Pydantic schema, or None on failure.
    """
    from app.infrastructure.llm.instructor_client import get_instructor_client, get_structured_model

    dim_schema = get_dimension_schema(dimension_key)
    client = get_instructor_client()
    model = get_structured_model()

    metrics_desc = get_metrics_description(dimension_key)
    metrics_hint = "\n".join(f"  - {k}: {v}" for k, v in metrics_desc.items())

    prompt = f"""分析以下规划报告，提取结构化摘要。

维度: {dimension_key} (Layer {layer})
报告字数: {len(content)}

规则提取已获得以下指标（请优先采用）:
{json.dumps(seed_metrics, ensure_ascii=False, indent=2) if seed_metrics else "（无）"}

还需提取的指标:
{metrics_hint}

要求:
- key_points: 3-5 条核心发现
- text_summary: 200 字以内自然语言概述
- metrics: 维度特定指标，无法提取用 null
- 维度专属字段: 从报告中提取，无法提取则 null/空

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

    # Override the call-injected fields
    summary.dimension_key = dimension_key
    summary.layer = layer
    summary.word_count = len(content)
    if summary.text_summary and len(summary.text_summary) > 200:
        summary.text_summary = summary.text_summary[:200]
    if len(summary.key_points) > 5:
        summary.key_points = summary.key_points[:5]

    # Normalize + merge + sync
    for k, v in seed_metrics.items():
        if k not in summary.metrics:
            summary.metrics[k] = v
    _sync_schema_fields_to_metrics(summary)

    return summary.model_dump_json(ensure_ascii=False)


def _sync_schema_fields_to_metrics(summary: BaseDimensionSummary) -> None:
    """Copy dimension-specific schema field values into metrics dict.

    Ensures conflict_detector can find values via _get_metric_value()
    regardless of whether they came from LLM or schema defaults.
    """
    for field_name in type(summary).model_fields:
        if field_name in ("dimension_key", "layer", "word_count",
                          "key_points", "text_summary", "metrics"):
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


def _default_summary_json(dimension_key: str, layer: int) -> str:
    """Return minimal valid summary JSON."""
    summary = BaseDimensionSummary(
        dimension_key=dimension_key,
        layer=layer,
        word_count=0,
    )
    return summary.model_dump_json(ensure_ascii=False)


__all__ = ["generate_structured_summary"]
