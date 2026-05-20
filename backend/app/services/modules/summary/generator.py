"""Structured summary generator using Flash LLM."""

import json
import re
from typing import Any, Dict, List, Optional

from app.utils.logger import get_logger
from .schema import get_dimension_schema, get_metrics_description, BaseDimensionSummary

logger = get_logger(__name__)


async def generate_structured_summary(
    dimension_key: str,
    layer: int,
    content: str,
    knowledge_sources: Optional[Any] = None,
) -> str:
    """Generate structured JSON summary for a dimension report.

    Returns JSON string compatible with BaseDimensionSummary schema.
    Falls back to regex extraction on LLM failure.
    """
    if not content:
        return _default_summary_json(dimension_key, layer)

    # Pre-extract via regex (always available as fallback/supplement)
    regex_metrics = _extract_metrics_regex(content, dimension_key)
    regex_key_points = _extract_key_points_regex(content)

    # Try Flash LLM structured generation
    try:
        llm_result = await _llm_generate(dimension_key, layer, content, regex_metrics)
        if llm_result:
            return llm_result
    except Exception as e:
        logger.warning(f"[summary] LLM generation failed for {dimension_key}: {e}")

    # Fallback: regex-only structured summary
    summary = BaseDimensionSummary(
        dimension_key=dimension_key,
        layer=layer,
        word_count=len(content),
        key_points=regex_key_points[:5],
        text_summary=content[:200],
        metrics=regex_metrics,
    )
    return summary.model_dump_json(ensure_ascii=False)


async def _llm_generate(
    dimension_key: str,
    layer: int,
    content: str,
    pre_extracted_metrics: Dict[str, Any],
) -> Optional[str]:
    """Use Flash LLM to generate structured summary."""
    from app.core.llm import create_flash_llm
    from .schema import get_dimension_schema, get_metrics_description

    # Use dimension-specific schema for field descriptions and validation
    dim_schema = get_dimension_schema(dimension_key)
    metrics_desc = get_metrics_description(dimension_key)

    # Build field descriptions from schema + metrics_desc
    field_lines = []
    if metrics_desc:
        field_lines = [f'  "{k}": {v}' for k, v in metrics_desc.items()]
    # Also include dimension-specific fields from the Pydantic model
    schema_fields = dim_schema.model_fields
    for fname, finfo in schema_fields.items():
        if fname not in ("dimension_key", "layer", "word_count", "key_points", "text_summary", "metrics") and fname not in metrics_desc:
            desc = finfo.description or fname
            field_lines.append(f'  "{fname}": {desc}')

    metrics_hint = ""
    if field_lines:
        metrics_hint = "可用字段:\n" + "\n".join(field_lines)

    prompt = f"""分析以下规划报告，提取结构化摘要。

维度: {dimension_key} (Layer {layer})

{metrics_hint}

请输出严格JSON格式（不要markdown代码块）:
{{
  "key_points": ["要点1", "要点2", "要点3"],
  "text_summary": "200字以内的概述",
  "metrics": {{"field1": value1, "field2": value2}}
}}

无法提取的字段使用null(数值)或空字符串/空数组。

报告内容（前3000字）:
{content[:3000]}"""

    llm = create_flash_llm(max_tokens=800, temperature=0.1)
    result = await llm.ainvoke(prompt)
    text = result.content.strip()

    # Extract JSON from LLM response
    json_str = _extract_json_from_text(text)
    if not json_str:
        return None

    parsed = json.loads(json_str)

    # Merge pre-extracted regex metrics (more reliable for numbers)
    parsed_metrics = parsed.get("metrics", {})
    for k, v in pre_extracted_metrics.items():
        if k not in parsed_metrics:
            parsed_metrics[k] = v
    parsed["metrics"] = parsed_metrics

    # Build summary using dimension-specific schema
    try:
        summary = dim_schema(
            dimension_key=dimension_key,
            layer=layer,
            word_count=len(content),
            key_points=parsed.get("key_points", [])[:5],
            text_summary=(parsed.get("text_summary", "") or "")[:200],
            metrics=parsed_metrics,
        )
    except Exception:
        # Fallback to base schema if dimension-specific validation fails
        summary = BaseDimensionSummary(
            dimension_key=dimension_key,
            layer=layer,
            word_count=len(content),
            key_points=parsed.get("key_points", [])[:5],
            text_summary=(parsed.get("text_summary", "") or "")[:200],
            metrics=parsed_metrics,
        )
    return summary.model_dump_json(ensure_ascii=False)


def _extract_json_from_text(text: str) -> Optional[str]:
    """Extract JSON object from LLM text response."""
    # Try direct parse
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r'^```\w*\n?', '', text)
        text = re.sub(r'\n?```$', '', text)
        text = text.strip()

    if text.startswith("{"):
        try:
            json.loads(text)
            return text
        except json.JSONDecodeError:
            pass

    # Find JSON block in text
    match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', text, re.DOTALL)
    if match:
        try:
            json.loads(match.group())
            return match.group()
        except json.JSONDecodeError:
            pass

    return None


def _extract_metrics_regex(content: str, dimension_key: str) -> Dict[str, Any]:
    """Extract key numeric metrics via regex patterns."""
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
