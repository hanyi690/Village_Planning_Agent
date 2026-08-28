"""L2 problem identification over typed observations only."""

from __future__ import annotations

from app.contracts.l2.l2_contracts import L2DecisionSet


def identify_problems(decision: L2DecisionSet) -> tuple[str, ...]:
    return tuple(
        item.statement.strip()
        for item in decision.objectives
        if item.statement.strip() and item.kind != "goal"
    )


__all__ = ["identify_problems"]
