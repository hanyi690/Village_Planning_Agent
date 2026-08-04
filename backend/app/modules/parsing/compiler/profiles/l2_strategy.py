"""L2 Strategy profile - compile one L2 dimension report into a fragment.

Full implementation lands in Wave D Task 4. This stub exists so the enum and
dispatch path are wired and tested first.
"""
from __future__ import annotations

from app.modules.schema.contracts.l2_contracts import L2StrategyFragment


def compile_l2_strategy(
    *,
    dimension_key: str,
    content: str,
    instruction: str,
    summary: str = "",
    report_id: str = "",
    run_id: str = "",
) -> L2StrategyFragment:
    raise NotImplementedError("L2_STRATEGY profile implementation lands in Wave D Task 4.")


__all__ = ["compile_l2_strategy"]
