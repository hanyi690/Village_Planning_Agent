"""Load and parse official planning markdown files for village spatial intent.

Replaces hardcoded _get_jintian_planning_text() with real document loading.
"""

from __future__ import annotations

import glob
from pathlib import Path
from typing import Dict, List, Optional

from app.core.settings import PROJECT_ROOT
from app.utils.logger import get_logger

logger = get_logger(__name__)

# Known planning document search patterns (ordered by priority)
_PLANNING_PATTERNS: List[str] = [
    # Official planning text (full document)
    "docs/MinerU_markdown_*村庄规划*文本*.md",
    # Planning refinement document
    "docs/MinerU_markdown_*规划细化*.md",
    # Planning approach document
    "docs/MinerU_markdown_*规划思路*.md",
    # Current status report (last resort)
    "docs/MinerU_markdown_*现状报告*.md",
]

# Village name aliases for fuzzy matching
_VILLAGE_ALIASES: Dict[str, List[str]] = {
    "金田村": ["金田村", "金田"],
    "金田村委会": ["金田村", "金田"],
}


class PlanningTextLoader:
    """Load planning markdown documents for intent parsing."""

    @staticmethod
    def load_village_planning_markdown(village_name: str) -> str:
        """Load planning markdown for a specific village.

        Searches docs/ directory for MinerU-extracted markdown files
        matching the village name. Returns the highest-priority document.

        Args:
            village_name: Village name (e.g., "金田村", "金田村委会")

        Returns:
            Markdown text content

        Raises:
            FileNotFoundError: If no planning markdown found
        """
        aliases = _VILLAGE_ALIASES.get(village_name, [village_name])

        for pattern in _PLANNING_PATTERNS:
            full_pattern = str(PROJECT_ROOT / pattern)
            matches = glob.glob(full_pattern)
            for match_path in matches:
                path = Path(match_path)
                # Check if file name contains any village alias
                filename = path.name
                if any(alias in filename for alias in aliases):
                    content = path.read_text(encoding="utf-8")
                    if content.strip():
                        logger.info(f"[PlanningTextLoader] Loaded: {path.name} ({len(content)} chars)")
                        return content
                    logger.warning(f"[PlanningTextLoader] Empty file: {path}")

        raise FileNotFoundError(
            f"No planning markdown found for village: {village_name}. "
            f"Searched in: {PROJECT_ROOT / 'docs/'}"
        )

    @staticmethod
    def list_available_documents(village_name: str = "") -> List[Dict[str, str]]:
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

                # If village specified, filter by alias
                if aliases and not any(alias in filename for alias in aliases):
                    continue

                # Determine document type
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
