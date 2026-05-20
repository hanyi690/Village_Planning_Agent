"""Summary parser with backward compatibility for plain-text summaries."""

import json
from typing import Any, Dict, Optional

from app.utils.logger import get_logger
from .schema import BaseDimensionSummary

logger = get_logger(__name__)


def parse_summary(
    summary_str: str,
    dimension_key: str = "",
    layer: int = 0,
) -> Dict[str, Any]:
    """Parse summary field, handling both JSON and plain-text formats.

    New format: JSON string matching BaseDimensionSummary schema.
    Old format: plain text (truncated content or LLM-generated prose).
    """
    if not summary_str:
        return _default_dict(dimension_key, layer)

    # Try JSON parse
    try:
        parsed = json.loads(summary_str)
        if isinstance(parsed, dict):
            # New structured format: has dimension_key
            if "dimension_key" in parsed:
                return parsed
            # Intermediate format from _generate_summary(): has summary/key_numbers
            if "summary" in parsed:
                return _convert_intermediate_format(parsed, dimension_key, layer)
    except (json.JSONDecodeError, TypeError):
        pass

    # Old format: plain text
    return {
        "dimension_key": dimension_key,
        "layer": layer,
        "word_count": len(summary_str),
        "key_points": [],
        "text_summary": summary_str[:200],
        "metrics": {},
    }


def _convert_intermediate_format(
    parsed: Dict[str, Any],
    dimension_key: str,
    layer: int,
) -> Dict[str, Any]:
    """Convert intermediate JSON format (from old _generate_summary) to new schema.

    Old format: {"summary": "...", "key_numbers": {...}, "key_findings": [...], ...}
    New format: {"dimension_key": "...", "layer": N, "word_count": N, "key_points": [...], ...}
    """
    return {
        "dimension_key": dimension_key,
        "layer": layer,
        "word_count": len(parsed.get("summary", "")),
        "key_points": parsed.get("key_findings", []),
        "text_summary": (parsed.get("summary", "") or "")[:200],
        "metrics": parsed.get("key_numbers", {}),
    }


def _default_dict(dimension_key: str, layer: int) -> Dict[str, Any]:
    """Return minimal default summary dict."""
    return {
        "dimension_key": dimension_key,
        "layer": layer,
        "word_count": 0,
        "key_points": [],
        "text_summary": "",
        "metrics": {},
    }


def format_summaries_for_prompt(
    summaries: Dict[str, Dict[str, Any]],
    max_text_summary_len: int = 200,
) -> str:
    """Format structured summaries into prompt text for downstream dimensions.

    Each dimension outputs:
    - dimension_key
    - key_points
    - metrics
    - text_summary
    """
    if not summaries:
        return ""

    parts = []
    for dim_key, summary in summaries.items():
        key_points = summary.get("key_points", [])
        metrics = summary.get("metrics", {})
        text_summary = summary.get("text_summary", "")

        lines = [f"【{dim_key}】"]

        if key_points:
            points_text = "；".join(key_points[:5])
            lines.append(f"关键要点：{points_text}")

        if metrics:
            metrics_items = [f"{k}={v}" for k, v in list(metrics.items())[:8]]
            lines.append(f"核心指标：{', '.join(metrics_items)}")

        if text_summary:
            lines.append(f"摘要：{text_summary[:max_text_summary_len]}")

        parts.append("\n".join(lines))

    return "\n\n".join(parts)


def get_key_points_from_summary(summary_str: str) -> list:
    """Extract key_points from a summary string (convenience function)."""
    parsed = parse_summary(summary_str)
    return parsed.get("key_points", [])
