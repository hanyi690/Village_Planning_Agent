"""Bounded tabular wire protocol shared by L1/L2/L3 prompts.

The protocol keeps large typed snapshots outside the model context.  Only a
small, flat page of rows is sent to the provider; refs let the runtime fetch
additional pages deterministically.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from app.infrastructure.context_runtime.table_renderer import build_bounded_table

DEFAULT_MAX_ROWS = 32
DEFAULT_MAX_COLUMNS = 12
DEFAULT_MAX_CHARS = 6200


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
    if not names or len(names) > max_columns or len(set(names)) != len(names):
        raise ValueError("LLM table columns must be unique and within the column budget")
    bounded, rendered = build_bounded_table(
        names,
        rows,
        max_rows=max_rows,
        max_chars=max_chars,
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
    "build_llm_table",
    "validate_flat_llm_rows",
]
