"""Bounded EXECUTE projection for delivery and structured outputs."""

from __future__ import annotations

from typing import Any

from app.infrastructure.context_runtime import ContextBudget, build_bounded_table


def build_execute_projection(result: Any, *, budget: ContextBudget | None = None) -> dict[str, Any]:
    rows = [
        {
            "task_id": str(getattr(item, "task_id", "")),
            "candidate_id": str(getattr(item, "candidate_id", "")),
            "status": str(getattr(item, "status", "")),
        }
        for item in list(getattr(result, "task_results", []) or [])
    ]
    rows, table = build_bounded_table(
        ("task_id", "candidate_id", "status"),
        rows,
        max_rows=(budget.max_rows if budget is not None else 80),
        max_chars=(budget.max_chars if budget is not None else 12000),
    )
    return {"rows": rows, "table": table, "count": len(rows)}


__all__ = ["build_execute_projection"]
