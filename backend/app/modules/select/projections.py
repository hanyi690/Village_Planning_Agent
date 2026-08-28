"""Bounded SELECT scenario projection."""

from __future__ import annotations

from typing import Any

from app.infrastructure.context_runtime import ContextBudget, build_bounded_table


def build_select_projection(scenario_set: Any, *, budget: ContextBudget | None = None) -> dict[str, Any]:
    rows = [
        {"scenario_id": str(getattr(item, "scenario_id", "")), "status": str(getattr(item, "status", ""))}
        for item in list(getattr(scenario_set, "scenarios", []) or [])
    ]
    rows, table = build_bounded_table(
        ("scenario_id", "status"),
        rows,
        max_rows=(budget.max_rows if budget is not None else 40),
        max_chars=(budget.max_chars if budget is not None else 12000),
    )
    return {"rows": rows, "table": table, "count": len(rows)}


__all__ = ["build_select_projection"]
