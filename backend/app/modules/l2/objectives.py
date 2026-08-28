"""L2 objective semantics; never resolves a spatial candidate."""

from __future__ import annotations

from app.contracts.l2.l2_contracts import L2DecisionSet


def objective_statements(decision: L2DecisionSet) -> tuple[str, ...]:
    return tuple(
        item.statement.strip()
        for item in decision.objectives
        if item.statement.strip()
    )


__all__ = ["objective_statements"]
