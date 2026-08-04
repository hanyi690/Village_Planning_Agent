"""L3 Planning profile - compile one L3 dimension report into a fragment.

Full implementation lands in Wave E Task 3. This stub exists so the enum and
dispatch path are wired and tested first.
"""
from __future__ import annotations

from app.modules.schema.contracts.l3_contracts import L3ProgramFragment


def compile_l3_planning(
    *,
    dimension_key: str,
    content: str,
    instruction: str,
    summary: str = "",
    report_id: str = "",
    run_id: str = "",
) -> L3ProgramFragment:
    raise NotImplementedError("L3_PLANNING profile implementation lands in Wave E Task 3.")


__all__ = ["compile_l3_planning"]
