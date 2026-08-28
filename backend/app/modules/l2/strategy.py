"""L2 strategy extraction from an already validated decision set."""

from __future__ import annotations

from app.contracts.l2.l2_contracts import L2Strategy


def strategy_statements(strategy: L2Strategy) -> tuple[str, ...]:
    return tuple(
        item.statement.strip()
        for item in strategy.strategy_rules
        if item.statement.strip()
    )


__all__ = ["strategy_statements"]
