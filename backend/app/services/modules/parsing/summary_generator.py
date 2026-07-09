"""Structured summary generation — Instructor + deterministic extraction.

Three-layer pipeline:
  Layer 1: Deterministic extraction via metric_anchors (zero LLM)
  Layer 2: Instructor schema-enforced generation via structured_output
  Layer 3: Fallback to regex-only on Instructor failure
"""

import json
import re
from typing import Any, Dict, List, Optional

from app.utils.logger import get_logger
from app.services.modules.parsing.schemas import (
    get_dimension_schema, BaseDimensionSummary, get_metrics_description,
)
from app.services.modules.parsing.metric_anchors import (
    extract_dimension_anchors, normalize_metric_keys,
)

logger = get_logger(__name__)

_BASE_SUMMARY_FIELDS = frozenset({
    "dimension_key", "layer", "word_count", "key_points", "text_summary", "metrics",
})


async def generate_structured_summary(
    dimension_key: str,
    layer: int,
    content: str,
    knowledge_sources: Optional[Any] = None,
) -> str:
    """Generate structured JSON summary for a dimension report."""
    if not content:
        return _default_summary_json(dimension_key, layer)

    # Layer 1: Deterministic extraction
    seed_metrics = extract_dimension_anchors(dimension_key, content)
    regex_key_points = _extract_key_points_regex(content)

    # Layer 2: Instructor schema-enforced generation
    try:
        result = await _instructor_generate(dimension_key, layer, content, seed_metrics)
        if result:
            return result
    except Exception as e:
        logger.warning(f"[summary] structured_parse failed for {dimension_key}: {e}")

    # Layer 3 fallback
    summary = BaseDimensionSummary(
        dimension_key=dimension_key,
        layer=layer,
        word_count=len(content),
        key_points=regex_key_points[:5],
        text_summary=content[:200],
        metrics=seed_metrics,
    )
    return summary.model_dump_json(ensure_ascii=False)


async def _instructor_generate(
    dimension_key: str,
    layer: int,
    content: str,
    seed_metrics: Dict[str, Any],
) -> Optional[str]:
    """Use structured_parse for Instructor-enforced summary generation."""
    from app.services.modules.parsing.structured_output import structured_parse

    dim_schema = get_dimension_schema(dimension_key)
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
        summary = await structured_parse(
            content=prompt,
            output_schema=dim_schema,
            dimension_key=dimension_key,
            max_tokens=800,
            temperature=0.1,
        )
    except Exception as e:
        logger.warning(f"[summary] structured_parse failed for {dimension_key}: {e}")
        return None

    if not isinstance(summary, BaseDimensionSummary):
        return None

    summary.dimension_key = dimension_key
    summary.layer = layer
    summary.word_count = len(content)
    if summary.text_summary and len(summary.text_summary) > 200:
        summary.text_summary = summary.text_summary[:200]
    if len(summary.key_points) > 5:
        summary.key_points = summary.key_points[:5]

    # Normalize + merge + sync
    summary.metrics = normalize_metric_keys(summary.metrics, dimension_key)
    for k, v in seed_metrics.items():
        if k not in summary.metrics:
            summary.metrics[k] = v
    _sync_schema_fields_to_metrics(summary)

    return summary.model_dump_json(ensure_ascii=False)


def _sync_schema_fields_to_metrics(summary: BaseDimensionSummary) -> None:
    """Copy dimension-specific schema field values into metrics dict."""
    for field_name in type(summary).model_fields:
        if field_name in _BASE_SUMMARY_FIELDS:
            continue
        value = getattr(summary, field_name, None)
        if value is not None and field_name not in summary.metrics:
            summary.metrics[field_name] = value


def _extract_key_points_regex(content: str) -> List[str]:
    """Extract key points from markdown headings and bold text."""
    points = []
    for m in re.finditer(r'###\s+(.+)', content):
        text = m.group(1).strip()
        if 4 <= len(text) <= 50:
            points.append(text)
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
