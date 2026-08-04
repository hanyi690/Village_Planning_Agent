"""Shared parse-compiler core - profile dispatch.

Wave B delivers the L1_OBSERVATION profile. Wave D delivers L2_STRATEGY.
Wave E delivers L3_PLANNING. REVISION is Wave F (roadmap row F). The
top-level agent/parse stage is a thin LangGraph wrapper over this core (Wave F).
"""
from __future__ import annotations

from app.modules.schema.contracts.l1_contracts import L1DimensionFragment
from app.modules.schema.contracts.l2_contracts import L2StrategyFragment
from app.modules.schema.contracts.l3_contracts import L3ProgramFragment
from app.modules.schema.contracts.parsing_contracts import CompilationProfile

from .diagnostics import collect_diagnostics
from .provenance import build_fragment_provenance


def compile_dimension_report(
    profile: CompilationProfile,
    *,
    dimension_key: str,
    content: str,
    instruction: str,
    summary: str = "",
    report_id: str = "",
    run_id: str = "",
) -> L1DimensionFragment | L2StrategyFragment | L3ProgramFragment | None:
    """Compile one dimension report into a typed fragment via the profile.

    Returns None if the profile produces no output (unsupported profile in
    this wave raises NotImplementedError instead).
    """
    if profile == CompilationProfile.L1_OBSERVATION:
        from .profiles.l1_observation import compile_l1_observation

        return compile_l1_observation(
            dimension_key=dimension_key,
            content=content,
            instruction=instruction,
            summary=summary,
            report_id=report_id,
            run_id=run_id,
        )
    if profile == CompilationProfile.L2_STRATEGY:
        from .profiles.l2_strategy import compile_l2_strategy

        return compile_l2_strategy(
            dimension_key=dimension_key,
            content=content,
            instruction=instruction,
            summary=summary,
            report_id=report_id,
            run_id=run_id,
        )
    if profile == CompilationProfile.L3_PLANNING:
        from .profiles.l3_planning import compile_l3_planning

        return compile_l3_planning(
            dimension_key=dimension_key,
            content=content,
            instruction=instruction,
            summary=summary,
            report_id=report_id,
            run_id=run_id,
        )
    if profile == CompilationProfile.REVISION:
        raise NotImplementedError("REVISION profile lands in Wave F (PARSE).")
    raise ValueError(f"unknown profile: {profile!r}")


__all__ = ["compile_dimension_report"]
