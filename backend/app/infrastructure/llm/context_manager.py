"""Central analysis-context projection and table rendering helpers.

Business stages may provide typed rows, but they do not choose a wire format.
JSON remains an internal persistence/digest format; prompts use these helpers.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from typing import Any


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


__all__ = ["render_table", "table_cell"]


def render_dependency_table(rows: Iterable[Mapping[str, Any]]) -> str:
    """Render the dependency projection used by L1/L2/L3 consumers."""

    return render_table(
        ("dimension_key", "layer", "version", "report_id",
         "instruction_status", "summary", "instruction"),
        rows,
    )


__all__.append("render_dependency_table")
