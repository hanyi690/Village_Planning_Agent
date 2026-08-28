"""Central analysis-context projection and table rendering helpers.

Business stages may provide typed rows, but they do not choose a wire format.
JSON remains an internal persistence/digest format; prompts use these helpers.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from .budgets import ContextBudget


def table_cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (Mapping, list, tuple)):
        value = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return str(value).replace("|", "\\|").replace("\n", "<br>")


def render_table(columns: Sequence[str], rows: Iterable[Mapping[str, Any]]) -> str:
    """Render typed prompt rows without leaking their Python/JSON container shape."""

    names = tuple(str(column) for column in columns)
    lines = [
        "| " + " | ".join(names) + " |",
        "| " + " | ".join("---" for _ in names) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(table_cell(row.get(column)) for column in names) + " |")
    return "\n".join(lines)


def build_bounded_table(
    columns: Sequence[str],
    rows: Iterable[Mapping[str, Any]],
    *,
    max_rows: int = 32,
    max_chars: int = 6200,
) -> tuple[list[dict[str, Any]], str]:
    """Apply the shared context budget and render one bounded table.

    Stage modules may declare the columns and their row projection, but the
    runtime owns row/character trimming and the wire-format rendering.  This
    keeps those two controls in one place and avoids each module accidentally
    calling ``render_table`` with an incomplete argument set.
    """

    bounded_rows = ContextBudget(max_rows=max_rows, max_chars=max_chars).trim_rows(
        [dict(row) for row in rows]
    )
    return bounded_rows, render_table(columns, bounded_rows)

__all__ = ["build_bounded_table", "render_table", "table_cell"]


def render_dependency_table(rows: Iterable[Mapping[str, Any]]) -> str:
    """Render the dependency projection used by L1/L2/L3 consumers."""

    return render_table(
        ("dimension_key", "layer", "version", "report_id",
         "instruction_status", "summary", "instruction"),
        rows,
    )


__all__.append("render_dependency_table")
