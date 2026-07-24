"""Document loading helpers - planning markdown, L3 reports.

Provides high-level loaders for non-spatial documents that feed the
PARSE/PLAN pipeline. Complements the document DataSourceDriver (low-level
file access via Catalog) with parsed/structured output.

Migrated from gis/data/loader.py (L3 report section) and
gis/data/text_loader.py (PlanningTextLoader). LLM/intent parsing logic
stays in gis/data/loader.py pending migration to tools/gis/parse.
"""

from __future__ import annotations

import glob
import json
import re
from pathlib import Path
from typing import Any, Dict

from app.core.settings import PROJECT_ROOT
from app.utils.logger import get_logger

logger = get_logger(__name__)

# L3 reports paths (used by PARSE agent and KG builder)
L3_REPORT_PATH = (
    PROJECT_ROOT / "output" / "experiments" / "rag" / "g1" / "iter0" / "layer3_reports.json"
)
L3_BASELINE_PATH = PROJECT_ROOT / "output" / "experiments" / "baseline" / "baseline_reports.json"

# Planning document search patterns (ordered by priority)
_PLANNING_PATTERNS: list[str] = [
    "docs/MinerU_markdown_*村庄规划*文本*.md",
    "docs/MinerU_markdown_*规划细化*.md",
    "docs/MinerU_markdown_*规划思路*.md",
    "docs/MinerU_markdown_*现状报告*.md",
]

# Village name aliases for fuzzy matching
_VILLAGE_ALIASES: Dict[str, list[str]] = {
    "金田村": ["金田村", "金田"],
    "金田村委会": ["金田村", "金田"],
}


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


def load_planning_text(village_name: str = "金田村委会") -> str:
    """Load planning markdown for a village.

    Searches docs/ for MinerU-extracted markdown matching the village name.
    Returns the highest-priority document.

    Args:
        village_name: Village name (e.g. "金田村", "金田村委会")

    Returns:
        Markdown text content.

    Raises:
        FileNotFoundError: If no planning markdown found.
    """
    aliases = _VILLAGE_ALIASES.get(village_name, [village_name])

    for pattern in _PLANNING_PATTERNS:
        full_pattern = str(PROJECT_ROOT / pattern)
        matches = glob.glob(full_pattern)
        for match_path in matches:
            path = Path(match_path)
            filename = path.name
            if any(alias in filename for alias in aliases):
                content = path.read_text(encoding="utf-8")
                if content.strip():
                    logger.info(
                        "[documents.loader] Loaded: %s (%d chars)",
                        path.name,
                        len(content),
                    )
                    return content
                logger.warning("[documents.loader] Empty file: %s", path)

    raise FileNotFoundError(
        f"No planning markdown found for village: {village_name}. "
        f"Searched in: {PROJECT_ROOT / 'docs/'}"
    )


def list_available_documents(village_name: str = "") -> list[Dict[str, str]]:
    """List all available planning documents for a village.

    Returns:
        List of {"path": str, "name": str, "type": str, "size_chars": int}
    """
    aliases = _VILLAGE_ALIASES.get(village_name, [village_name]) if village_name else []
    results = []

    for pattern in _PLANNING_PATTERNS:
        full_pattern = str(PROJECT_ROOT / pattern)
        matches = glob.glob(full_pattern)
        for match_path in matches:
            path = Path(match_path)
            filename = path.name

            if aliases and not any(alias in filename for alias in aliases):
                continue

            doc_type = "unknown"
            if "文本" in filename:
                doc_type = "planning_text"
            elif "规划细化" in filename:
                doc_type = "planning_detail"
            elif "规划思路" in filename:
                doc_type = "planning_approach"
            elif "现状报告" in filename:
                doc_type = "current_status"

            try:
                size = len(path.read_text(encoding="utf-8"))
            except Exception:
                size = 0

            results.append({
                "path": str(path),
                "name": filename,
                "type": doc_type,
                "size_chars": size,
            })

    return results


__all__ = [
    "load_l3_reports",
    "load_planning_text",
    "list_available_documents",
    "L3_REPORT_PATH",
    "L3_BASELINE_PATH",
]
