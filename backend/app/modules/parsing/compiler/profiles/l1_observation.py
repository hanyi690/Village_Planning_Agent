"""L1 Observation profile - compile one L1 dimension report into a fragment.

MINIMAL STUB (Task 2) - replaced by full implementation in Task 3.
"""
from __future__ import annotations

from app.modules.schema.contracts.l1_contracts import L1DimensionFragment
from app.modules.schema.contracts.parsing_contracts import (
    CompilationProfile,
    CompilerTrace,
)

from ..diagnostics import collect_diagnostics
from ..provenance import build_fragment_provenance


def compile_l1_observation(
    *,
    dimension_key: str,
    content: str,
    instruction: str,
    summary: str = "",
    report_id: str = "",
    run_id: str = "",
) -> L1DimensionFragment:
    return L1DimensionFragment(
        dimension_key=dimension_key,
        facts=[],
        constraints=[],
        issues=[],
        opportunities=[],
        evidence_gaps=[],
        classification_refs=[],
        spatial_facts=[],
        diagnostics=collect_diagnostics(dimension_key, content or "", instruction),
        provenance=build_fragment_provenance(
            dimension_key, report_id, run_id, ["stub"]
        ),
        trace=CompilerTrace(
            profile=CompilationProfile.L1_OBSERVATION,
            steps=["stub"],
        ),
    )


__all__ = ["compile_l1_observation"]
