"""Shared bounded row/character budgets for stage projections."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ContextBudget:
    max_rows: int = 32
    max_chars: int = 6200

    def trim_rows(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        selected: list[dict[str, Any]] = []
        used = 0
        for row in rows[: max(1, self.max_rows)]:
            row_chars = len(str(row))
            if selected and used + row_chars > max(1, self.max_chars):
                break
            selected.append(row)
            used += row_chars
        return selected


__all__ = ["ContextBudget"]
