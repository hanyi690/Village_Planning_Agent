"""Deterministic markdown table parser — replaces LLM for extract_tables.

Parses markdown tables (pipe-delimited rows) into structured dicts.
Also splits documents by ## / ### headers for section classification.

Token savings: 3K-5K per table section (100% LLM → 0 LLM).
"""

from __future__ import annotations

import re
from typing import List, Dict, Optional


# ── Table parsing ────────────────────────────────────────────────────

def parse_markdown_tables(text: str) -> List[Dict]:
    """Parse pipe-delimited markdown tables from text.

    Returns list of {headers: [str], rows: [[str, ...], ...]} dicts.
    Handles:
      - Standard | col1 | col2 | format
      - Multi-row tables with separator lines (|---|---|)
      - Empty lines as table boundaries
      - Headers-first: first non-separator, non-empty line = headers

    Example:
        >>> text = "| 项目 | 面积 |\n|------|------|\n| A | 100 |\n| B | 200 |"
        >>> tables = parse_markdown_tables(text)
        >>> tables[0]["headers"]  # ["项目", "面积"]
        >>> tables[0]["rows"][0]  # ["A", "100"]
    """
    tables: List[Dict] = []
    lines = text.split("\n")
    in_table = False
    current_headers: List[str] = []
    current_rows: List[List[str]] = []

    for line in lines:
        stripped = line.strip()

        # Empty line: flush current table
        if not stripped:
            if in_table and current_headers:
                tables.append({"headers": current_headers, "rows": current_rows})
                current_headers, current_rows = [], []
            in_table = False
            continue

        # Must contain pipe to be a table row
        if "|" not in stripped:
            if in_table and current_headers:
                tables.append({"headers": current_headers, "rows": current_rows})
                current_headers, current_rows = [], []
            in_table = False
            continue

        # Split cells, strip whitespace
        cells = [c.strip() for c in stripped.strip("|").split("|")]

        # Detect separator line: |---|:---| or similar
        if _is_separator_line(cells):
            in_table = True
            continue

        if in_table:
            # Continuation row
            current_rows.append(cells)
        elif not current_headers:
            # First line = headers
            current_headers = cells
            in_table = True

    # Flush remaining
    if current_headers:
        tables.append({"headers": current_headers, "rows": current_rows})

    return tables


def _is_separator_line(cells: List[str]) -> bool:
    """Check if cells look like a markdown separator: ---, :---, ---:, :---:"""
    return all(re.match(r"^:?-{2,}:?$", c) for c in cells if c)


# ── Table detection ──────────────────────────────────────────────────

def detect_table(text: str) -> bool:
    """Detect if text contains a markdown table (pipe-delimited)."""
    return bool(re.search(r"\|.+\|\s*$", text, re.MULTILINE))


# ── Header-based section splitting ───────────────────────────────────

def split_by_headers(text: str) -> List[Dict[str, str]]:
    """Split markdown text by ## or ### headers.

    Returns list of {title: str, content: str, level: int} dicts.
    Preserves header levels for hierarchy-aware processing.

    Example:
        >>> text = "## 规划目标\\n内容A\\n## 空间布局\\n内容B"
        >>> sections = split_by_headers(text)
        >>> sections[0] == {"title": "规划目标", "content": "内容A", "level": 2}
    """
    sections: List[Dict[str, str]] = []
    pattern = re.compile(r"^(#{1,3})\s+(.+)$", re.MULTILINE)
    matches = list(pattern.finditer(text))

    if not matches:
        # No headers found: return entire text as one section
        if text.strip():
            sections.append({"title": "Full Document", "content": text.strip(), "level": 0})
        return sections

    for i, m in enumerate(matches):
        level = len(m.group(1))
        title = m.group(2).strip()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        content = text[start:end].strip()
        sections.append({"title": title, "content": content, "level": level})

    return sections
