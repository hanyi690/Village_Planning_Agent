"""Structured summary generation — pure Instructor path.

Two-layer pipeline:
  Layer 0: GIS GeoJSON direct computation (deterministic, zero LLM)
  Layer 2: Instructor schema-enforced generation (with retry)

Layer 1 (extract_dimension_anchors regex) and Layer 3 (regex fallback)
have been removed. Instructor is the sole text extraction path.
"""

import json
from typing import Any, Dict, List, Optional

from app.utils.logger import get_logger
from app.services.modules.parsing.schemas import (
    get_dimension_schema, BaseDimensionSummary, get_metrics_description,
)

logger = get_logger(__name__)

_BASE_SUMMARY_FIELDS = frozenset({
    "dimension_key", "layer", "word_count", "key_points", "text_summary", "metrics",
})

# GIS-relevant dimensions that benefit from GeoJSON direct computation
_GIS_DIMENSIONS = frozenset({
    "land_use", "spatial_structure", "land_use_planning",
    "ecological", "ecological_green", "settlement_planning",
})


async def generate_structured_summary(
    dimension_key: str,
    layer: int,
    content: str,
    knowledge_sources: Optional[Any] = None,
    max_retries: int = 2,
) -> str:
    """Generate structured JSON summary — pure Instructor path.

    Layer 0: GIS GeoJSON direct computation (if applicable)
    Layer 2: Instructor schema-enforced generation (with retry)
    Fallback: Empty key_points, metrics only from GIS computation
    """
    if not content:
        return _default_summary_json(dimension_key, layer)

    # Layer 0: GIS direct computation (deterministic, zero LLM)
    gis_metrics = _extract_gis_metrics(dimension_key, content)

    # Layer 2: Instructor with retry
    for attempt in range(max_retries + 1):
        try:
            result = await _instructor_generate(dimension_key, layer, content, gis_metrics)
            if result:
                return result
        except Exception as e:
            logger.warning(
                "[summary] Instructor attempt %d/%d failed for %s: %s",
                attempt + 1, max_retries + 1, dimension_key, e,
            )

    # Fallback: empty key_points (no regex), GIS metrics only
    logger.warning(
        "[summary] All Instructor attempts failed for %s, using empty fallback",
        dimension_key,
    )
    summary = BaseDimensionSummary(
        dimension_key=dimension_key,
        layer=layer,
        word_count=len(content),
        key_points=[],
        text_summary=content[:200],
        metrics=gis_metrics,
    )
    return summary.model_dump_json(ensure_ascii=False)


async def _instructor_generate(
    dimension_key: str,
    layer: int,
    content: str,
    gis_metrics: Dict[str, Any],
) -> Optional[str]:
    """Use structured_parse for Instructor-enforced summary generation."""
    from app.services.modules.parsing.structured_output import structured_parse

    dim_schema = get_dimension_schema(dimension_key)
    metrics_desc = get_metrics_description(dimension_key)
    metrics_hint = "\n".join(f"  - {k}: {v}" for k, v in metrics_desc.items())

    prompt = f"""分析以下规划报告，提取结构化摘要。

维度: {dimension_key} (Layer {layer})
报告字数: {len(content)}

GIS 计算已获得以下指标（请优先采用）:
{json.dumps(gis_metrics, ensure_ascii=False, indent=2) if gis_metrics else "（无）"}

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
        logger.warning("[summary] structured_parse failed for %s: %s", dimension_key, e)
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

    # GIS metrics fill gaps that Instructor couldn't extract
    for k, v in gis_metrics.items():
        if k not in summary.metrics:
            summary.metrics[k] = v

    _sync_schema_fields_to_metrics(summary)

    return summary.model_dump_json(ensure_ascii=False)


def _extract_gis_metrics(
    dimension_key: str,
    content: str,
) -> Dict[str, Any]:
    """Extract metrics from GIS GeoJSON data (Layer 0 only).

    Only runs for GIS-relevant dimensions. Returns deterministic
    area/coverage values computed from GeoJSON properties.
    """
    if dimension_key not in _GIS_DIMENSIONS:
        return {}

    try:
        from app.services.modules.parsing.metric_anchors import extract_gis_anchors
        return extract_gis_anchors(dimension_key, content)
    except Exception as e:
        logger.warning("[summary] GIS anchor extraction failed for %s: %s", dimension_key, e)
        return {}


def _sync_schema_fields_to_metrics(summary: BaseDimensionSummary) -> None:
    """Copy dimension-specific schema field values into metrics dict."""
    for field_name in type(summary).model_fields:
        if field_name in _BASE_SUMMARY_FIELDS:
            continue
        value = getattr(summary, field_name, None)
        if value is not None and field_name not in summary.metrics:
            summary.metrics[field_name] = value


def _default_summary_json(dimension_key: str, layer: int) -> str:
    """Return minimal valid summary JSON."""
    summary = BaseDimensionSummary(
        dimension_key=dimension_key,
        layer=layer,
        word_count=0,
    )
    return summary.model_dump_json(ensure_ascii=False)
