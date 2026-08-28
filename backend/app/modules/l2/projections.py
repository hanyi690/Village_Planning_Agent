"""Bounded L2 projection built from the reloaded L1 fact table."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.contracts.l1.l1_contracts import L1Snapshot
from app.infrastructure.context_runtime import ContextBudget, build_bounded_table


def build_l2_projection(
    snapshot: L1Snapshot,
    *,
    budget: ContextBudget | None = None,
) -> dict[str, Any]:
    rows = [
        {
            "fact_id": fact.fact_id,
            "dimension": fact.dimension_key,
            "statement": fact.statement,
            "inference": fact.inference_level,
            "source_refs": ",".join(fact.source_refs[:3]),
        }
        for fact in snapshot.fact_records
    ]
    rows, fact_table = build_bounded_table(
        ("fact_id", "dimension", "statement", "inference", "source_refs"),
        rows,
        max_rows=(budget.max_rows if budget is not None else 32),
        max_chars=(budget.max_chars if budget is not None else 6200),
    )
    return {
        "context_version": snapshot.context_version,
        "context_fingerprint": snapshot.context_fingerprint,
        "fact_rows": rows,
        "fact_table": fact_table,
    }


__all__ = ["build_l2_projection"]
