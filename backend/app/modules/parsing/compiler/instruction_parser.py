"""【INSTRUCTION】 parsing - shared by L1 and (Wave F) L3 profiles.

Wraps app.modules.parsing.tables for structural table extraction. The L1
profile uses the facility/project/zone rows as spatial facts; the L3 profile
will map them to typed targets.
"""
from __future__ import annotations

from typing import Any

_INSTRUCTION_MARKER = "【INSTRUCTION】"


def split_content_instruction(content_with_instruction: str) -> tuple[str, str]:
    """Split a report into (display_content, instruction_section).

    Local reimplementation of ReportStore.split_instruction semantics so the
    parsing layer does not depend on app.services.
    """
    if not content_with_instruction:
        return (content_with_instruction or "", "")
    idx = content_with_instruction.find(_INSTRUCTION_MARKER)
    if idx < 0:
        recovered = _recover_l3_instruction_table(content_with_instruction)
        if recovered is not None:
            display, table = recovered
            return (display.rstrip(), f"{_INSTRUCTION_MARKER}\n{table.strip()}")
        return (content_with_instruction, "")
    display = content_with_instruction[:idx].rstrip()
    instruction = content_with_instruction[idx:].strip()
    return (display, instruction)


def _recover_l3_instruction_table(content: str) -> tuple[str, str] | None:
    """Recover only model-emitted structured rows when the marker is absent."""
    lines = (content or "").splitlines()
    categories = {"项目", "功能分区", "设施", "轴线", "道路"}
    candidates: list[tuple[int, str]] = []
    for index, raw in enumerate(lines):
        line = raw.strip()
        if line.startswith("-"):
            line = line[1:].strip()
        if not (line.startswith("|") and line.endswith("|")):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) >= 5 and cells[0] in categories and cells[1]:
            candidates.append((index, "| " + " | ".join(cells[:5]) + " |"))
    if not candidates:
        return None
    selected: list[tuple[int, str]] = []
    for item in candidates:
        if not selected or item[0] <= selected[-1][0] + 1:
            selected.append(item)
        else:
            break
    if not selected:
        return None
    start, end = selected[0][0], selected[-1][0]
    table = (
        "| 类型 | 名称 | 位置 | 描述 | 规模 |\n"
        "| :--- | :--- | :--- | :--- | :--- |\n"
        + "\n".join(row for _, row in selected)
    )
    display = "\n".join(
        line for index, line in enumerate(lines) if not (start <= index <= end)
    )
    return display, table


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
    from app.modules.parsing.tables import _iter_tables

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


__all__ = ["split_content_instruction", "parse_instruction_tables"]
