"""Bounded tabular wire protocol shared by L1/L2/L3 prompts.

The protocol keeps large typed snapshots outside the model context.  Only a
small, flat page of rows is sent to the provider; refs let the runtime fetch
additional pages deterministically.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from app.infrastructure.context_runtime.table_renderer import render_table

DEFAULT_MAX_ROWS = 32
DEFAULT_MAX_COLUMNS = 12
DEFAULT_MAX_CHARS = 6200
DEFAULT_MAX_CELL_CHARS = 600
DEFAULT_MAX_LIST_ITEMS = 16


def _bounded_cell(value: Any) -> Any:
    if value is None or isinstance(value, (int, float, bool)):
        return value
    if isinstance(value, str):
        if len(value) <= DEFAULT_MAX_CELL_CHARS:
            return value
        omitted = len(value) - DEFAULT_MAX_CELL_CHARS
        return value[:DEFAULT_MAX_CELL_CHARS] + f"…[{omitted} chars omitted]"
    if isinstance(value, Mapping):
        raise ValueError(
            "LLM table cells cannot contain mappings; project explicit columns"
        )
    if isinstance(value, (list, tuple, set, frozenset)):
        values = list(value)
        if any(
            isinstance(item, (Mapping, list, tuple, set, frozenset))
            for item in values
        ):
            raise ValueError("LLM table cells must be scalar or flat scalar lists")
        bounded = [
            _bounded_cell(item)
            for item in values[:DEFAULT_MAX_LIST_ITEMS]
        ]
        if len(values) > DEFAULT_MAX_LIST_ITEMS:
            bounded.append(
                f"…[{len(values) - DEFAULT_MAX_LIST_ITEMS} items omitted]"
            )
        return bounded
    return _bounded_cell(str(value))


def build_llm_table(
    columns: Sequence[str],
    rows: Sequence[Mapping[str, Any]],
    *,
    max_rows: int = DEFAULT_MAX_ROWS,
    max_columns: int = DEFAULT_MAX_COLUMNS,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> tuple[list[dict[str, Any]], str]:
    """Validate columns and return a bounded prompt table."""

    names = [str(column).strip() for column in columns]
    hard_columns = min(DEFAULT_MAX_COLUMNS, max(1, int(max_columns)))
    hard_rows = min(DEFAULT_MAX_ROWS, max(1, int(max_rows)))
    hard_chars = min(DEFAULT_MAX_CHARS, max(128, int(max_chars)))
    if not names or len(names) > hard_columns or len(set(names)) != len(names):
        raise ValueError("LLM table columns must be unique and within the column budget")
    normalized: list[dict[str, Any]] = []
    for raw_row in rows[:hard_rows]:
        if not isinstance(raw_row, Mapping):
            raise ValueError("LLM table rows must be mappings")
        normalized.append({
            name: _bounded_cell(raw_row.get(name))
            for name in names
        })
    bounded: list[dict[str, Any]] = []
    rendered = render_table(names, bounded)
    for row in normalized:
        candidate = [*bounded, row]
        candidate_table = render_table(names, candidate)
        if len(candidate_table) > hard_chars:
            break
        bounded = candidate
        rendered = candidate_table
    if normalized and not bounded:
        raise ValueError(
            "one LLM table row exceeds the global rendered character budget"
        )
    return bounded, rendered


def validate_flat_llm_rows(
    rows: Any,
    *,
    required_columns: Sequence[str],
    max_rows: int = DEFAULT_MAX_ROWS,
    max_depth: int = 2,
) -> list[dict[str, Any]]:
    """Reject nested/oversized provider output before artifact assembly."""

    if not isinstance(rows, list) or len(rows) > max_rows:
        raise ValueError("LLM output must be one bounded list of rows")
    required = {str(value) for value in required_columns}

    def depth(value: Any) -> int:
        if isinstance(value, Mapping):
            return 1 + max((depth(item) for item in value.values()), default=0)
        if isinstance(value, (list, tuple)):
            return 1 + max((depth(item) for item in value), default=0)
        return 0

    result: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            raise ValueError("each LLM output row must be an object")
        if required - set(str(key) for key in row):
            raise ValueError("LLM output row is missing required columns")
        if depth(row) > max_depth:
            raise ValueError("nested LLM output exceeds the flat-row depth budget")
        result.append({str(key): value for key, value in row.items()})
    return result


__all__ = [
    "DEFAULT_MAX_ROWS",
    "DEFAULT_MAX_COLUMNS",
    "DEFAULT_MAX_CHARS",
    "DEFAULT_MAX_CELL_CHARS",
    "build_llm_table",
    "validate_flat_llm_rows",
]
