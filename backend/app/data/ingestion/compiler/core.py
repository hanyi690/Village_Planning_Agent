"""Shared report projection compiler for L1 and L2 only.

L3 is a typed claims boundary and deliberately does not use this parser.
"""
from __future__ import annotations

from app.contracts.domain.l1_contracts import L1DimensionFragment
from app.contracts.domain.l2_contracts import L2StrategyFragment
from app.contracts.workflow.parsing_contracts import CompilationProfile

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
) -> L1DimensionFragment | L2StrategyFragment | None:
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
    raise ValueError(f"unknown profile: {profile!r}")


__all__ = ["compile_dimension_report"]
