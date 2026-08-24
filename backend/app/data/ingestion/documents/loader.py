"""Document loading helpers for explicitly configured legacy L3 reports.

Session-owned planning inputs are loaded by the session catalog boundary;
this module intentionally does not search the repository for planning files.

The remaining helper is retained only for explicitly configured legacy L3
report fixtures used by offline tooling.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict

from app.core.settings import PROJECT_ROOT
from app.infrastructure.logging import get_logger

logger = get_logger(__name__)

# L3 reports paths (used by PARSE agent and KG builder)
L3_REPORT_PATH = (
    PROJECT_ROOT / "output" / "experiments" / "rag" / "g1" / "iter0" / "layer3_reports.json"
)
L3_BASELINE_PATH = PROJECT_ROOT / "output" / "experiments" / "baseline" / "baseline_reports.json"

def load_l3_reports() -> Dict[str, Any]:
    """Load L3 reports from available paths.

    Tries RAG path first, then baseline fallback.

    Returns:
        {dim_key: {"summary": {"metrics": {...}}, "content": "..."}}
    """
    raw = _load_raw_reports()

    result: Dict[str, Any] = {}
    for dim_key, content in raw.items():
        if not isinstance(content, str):
            continue
        result[dim_key] = {
            "summary": {"metrics": _extract_metrics_regex(content)},
            "content": content,
        }
    return result


def _load_raw_reports() -> Dict[str, str]:
    """Load raw L3 report strings from JSON file."""
    for path in [L3_REPORT_PATH, L3_BASELINE_PATH]:
        if path.exists():
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            return data.get("reports", {})
    logger.warning("[documents.loader] No L3 reports found")
    return {}


def _extract_metrics_regex(content: str) -> Dict[str, Any]:
    """Extract numeric metrics from L3 report content via regex."""
    metrics: Dict[str, Any] = {}
    patterns = [
        (r"([\d.]+)\s*公顷", "area_ha"),
        (r"([\d.]+)\s*亩", "area_mu"),
        (r"(\d+)\s*人", "population"),
        (r"(\d+)\s*户", "households"),
        (r"([\d.]+)\s*%", "percentage"),
        (r"([\d.]+)\s*万元", "amount_wan_yuan"),
        (r"([\d.]+)\s*km", "length_km"),
        (r"([\d.]+)\s*m[²2]", "area_sqm"),
    ]
    for pat, key in patterns:
        m = re.search(pat, content)
        if m:
            val = m.group(1)
            metrics[key] = float(val) if "." in val else int(val)

    specific = [
        (r"建设用地.*?([\d.]+)\s*公顷", "建设用地规模_公顷"),
        (r"耕地.*?([\d.]+)\s*公顷", "耕地保有量_公顷"),
        (r"生态保护红线.*?([\d.]+)\s*公顷", "生态保护红线面积"),
        (r"永久基本农田.*?([\d.]+)\s*公顷", "永久基本农田_公顷"),
        (r"森林覆盖率.*?([\d.]+)\s*%", "森林覆盖率_百分比"),
        (r"林地.*?([\d.]+)\s*公顷", "林地保有量_公顷"),
    ]
    for pat, key in specific:
        m = re.search(pat, content)
        if m:
            metrics[key] = float(m.group(1))

    return metrics


__all__ = [
    "load_l3_reports",
    "L3_REPORT_PATH",
    "L3_BASELINE_PATH",
]
