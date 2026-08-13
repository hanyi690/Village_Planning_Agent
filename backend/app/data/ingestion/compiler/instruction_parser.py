"""【INSTRUCTION】 parsing - shared by L1 and (Wave F) L3 profiles.

Wraps app.data.ingestion.tables for structural table extraction. The L1
profile uses the facility/project/zone rows as spatial facts; the L3 profile
will map them to typed targets.
"""
from __future__ import annotations

from typing import Any

_INSTRUCTION_MARKER = "【INSTRUCTION】"
_FIXED_HEADER = "| 类型 | 名称 | 位置 | 描述 | 规模 |"


def split_content_instruction(content_with_instruction: str) -> tuple[str, str]:
    """Split a report into (display_content, instruction_section).

    Local reimplementation of ReportStore.split_instruction semantics so the
    parsing layer stays decoupled from the runtime service layer.
    """
    if not content_with_instruction:
        return (content_with_instruction or "", "")
    idx = content_with_instruction.find(_INSTRUCTION_MARKER)
    if idx < 0:
        return (content_with_instruction, "")
    display = content_with_instruction[:idx].rstrip()
    instruction = content_with_instruction[idx:].strip()
    return (display, instruction)


def normalize_trailing_instruction_marker(content: str) -> tuple[str, bool]:
    """Insert only the transport marker before an exact trailing fixed table."""
    if not content or _INSTRUCTION_MARKER in content:
        return content or "", False
    index = content.rfind(_FIXED_HEADER)
    if index < 0:
        return content, False
    table = content[index:].strip()
    lines = table.splitlines()
    if len(lines) < 3 or lines[0].strip() != _FIXED_HEADER:
        return content, False
    separator = [cell.strip() for cell in lines[1].strip().strip("|").split("|")]
    if len(separator) != 5 or not all(set(cell) <= {":", "-"} for cell in separator):
        return content, False
    data_rows = [line for line in lines[2:] if line.strip().startswith("|")]
    if not data_rows:
        return content, False
    display = content[:index].rstrip()
    return f"{display}\n\n{_INSTRUCTION_MARKER}\n{table}", True


def parse_instruction_tables(instruction: str) -> dict[str, list[dict[str, Any]]]:
    """Extract structured table rows from an INSTRUCTION segment.

    Returns a dict keyed by table type:
      - facility_rows: tables whose header contains 设施/数量
      - project_rows:  tables whose header contains 项目名称/工程名称
      - zone_rows:     tables whose header contains 分区/面积
    Empty dict when instruction is blank or has no tables.  L1's generic
    ``类型|名称|位置|描述|规模`` table is returned as ``l1_rows`` so the
    observation compiler can build location facts from the private contract
    instead of mining prose.
    """
    if not instruction:
        return {}
    from app.data.ingestion.tables import _iter_tables

    result: dict[str, list[dict[str, Any]]] = {}
    for header, rows in _iter_tables(instruction):
        joined = "|".join(header)
        normalized = {str(cell).strip() for cell in header}
        if {"类型", "名称", "位置"}.issubset(normalized):
            key = "l1_rows"
        elif "设施" in joined or "数量" in joined:
            key = "facility_rows"
        elif "项目名称" in joined or "工程名称" in joined:
            key = "project_rows"
        elif "分区" in joined or "面积" in joined:
            key = "zone_rows"
        else:
            continue
        batch = result.setdefault(key, [])
        for row in rows:
            batch.append(dict(zip(header, row)))
    return result


__all__ = [
    "split_content_instruction",
    "normalize_trailing_instruction_marker",
    "parse_instruction_tables",
]
