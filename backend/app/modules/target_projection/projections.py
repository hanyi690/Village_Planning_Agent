"""Bounded TARGET_PROJECTION context projection."""

from __future__ import annotations

from typing import Any

from app.infrastructure.context_runtime import ContextBudget, build_bounded_table


def build_target_projection_projection(
    result: Any,
    *,
    budget: ContextBudget | None = None,
) -> dict[str, Any]:
    rows = [
        {
            "intervention_id": str(getattr(item, "intervention_id", "")),
            "reference_kind": str(getattr(getattr(item, "reference", None), "kind", "")),
            "unresolved_reason": str(getattr(item, "unresolved_reason", "") or ""),
        }
        for item in list(getattr(result, "spatial_reference_specs", []) or [])
    ]
    rows, table = build_bounded_table(
        ("intervention_id", "reference_kind", "unresolved_reason"),
        rows,
        max_rows=(budget.max_rows if budget is not None else 80),
        max_chars=(budget.max_chars if budget is not None else 12000),
    )
    return {"rows": rows, "table": table, "count": len(rows)}


__all__ = ["build_target_projection_projection"]
