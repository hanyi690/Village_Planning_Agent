"""Shared report projection compiler for the L1 display snapshot only.

L2 and L3 are typed model boundaries.  Their authoritative outputs are
validated where they are generated and are never reconstructed from prose.
"""
from __future__ import annotations

from app.contracts.domain.l1_contracts import L1Snapshot
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
) -> L1Snapshot | None:
    """Compile one dimension report into a typed stage snapshot via the profile.

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
    raise ValueError(f"unknown profile: {profile!r}")


__all__ = ["compile_dimension_report"]
