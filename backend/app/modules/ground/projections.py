"""Bounded GROUND projection for shared context construction."""

from __future__ import annotations

from typing import Any

from app.infrastructure.context_runtime import ContextBudget, build_bounded_table


def build_ground_projection(result: Any, *, budget: ContextBudget | None = None) -> dict[str, Any]:
    rows = [
        {
            "candidate_id": str(getattr(item, "candidate_id", "")),
            "target_ref": str(getattr(item, "target_ref", "")),
            "status": str(getattr(item, "status", "")),
            "source_ref_count": len(getattr(item, "source_refs", []) or []),
        }
        for item in list(getattr(result, "candidates", []) or [])
    ]
    rows, table = build_bounded_table(
        ("candidate_id", "target_ref", "status", "source_ref_count"),
        rows,
        max_rows=(budget.max_rows if budget is not None else 80),
        max_chars=(budget.max_chars if budget is not None else 12000),
    )
    return {"rows": rows, "table": table, "count": len(rows)}


__all__ = ["build_ground_projection"]
