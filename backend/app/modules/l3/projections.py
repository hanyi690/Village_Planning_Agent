"""Bounded L3 projection for shared context construction."""

from __future__ import annotations

from typing import Any

from app.infrastructure.context_runtime import ContextBudget, build_bounded_table


def build_l3_projection(program: Any, *, budget: ContextBudget | None = None) -> dict[str, Any]:
    rows = []
    for item in list(getattr(program, "interventions", []) or []):
        rows.append({
            "intervention_id": str(getattr(item, "intervention_id", "")),
            "name": str(getattr(item, "name", "")),
            "action": str(getattr(item, "action", "")),
            "spatial_requirement_count": len(getattr(item, "spatial_requirements", []) or []),
        })
    rows, table = build_bounded_table(
        ("intervention_id", "name", "action", "spatial_requirement_count"),
        rows,
        max_rows=(budget.max_rows if budget is not None else 80),
        max_chars=(budget.max_chars if budget is not None else 12000),
    )
    return {"rows": rows, "table": table, "count": len(rows)}


__all__ = ["build_l3_projection"]
