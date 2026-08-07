"""PARSE route node - deterministic ambiguity check (Hybrid routing skeleton).

Wave F routes a compiled IntentCompilationResult through the top-level PARSE
subgraph. Pure function: no LLM calls, no I/O. The LLM patch route is
uninvoked in Wave F - callers treat ``llm_patch`` as a human-review fallback.
"""
from __future__ import annotations

from typing import Literal

from app.modules.schema.contracts.parse_result_contracts import (
    IntentCompilationResult,
    ParseDiagnostic,
)

_ROUTE_LLM_THRESHOLD = 3


def route_compilation(
    result: IntentCompilationResult,
    diagnostics: list[ParseDiagnostic],
) -> Literal["merge", "llm_patch", "human_review"]:
    """Decide the top-level PARSE route from the compile diagnostics.

    - Any ``error`` diagnostic -> ``human_review`` (unsafe to auto-patch)
    - ``>= 3`` AMBIGUOUS_REFERENCE diagnostics -> ``llm_patch`` (LLM patch
      route, uninvoked in Wave F)
    - Otherwise -> ``merge`` (deterministic patch merger)
    """
    if any(d.severity == "error" for d in diagnostics):
        return "human_review"
    ambiguous = sum(1 for d in diagnostics if d.code == "AMBIGUOUS_REFERENCE")
    # Partial spatial coverage is safe to continue: mapped interventions can
    # be grounded and the unresolved ones remain explicit diagnostics for
    # VALIDATE/HUMAN. Only an entirely unmappable program needs the expensive
    # patch/review route; otherwise one verbose L3 report can deadlock PARSE
    # despite having usable spatial references.
    if ambiguous >= _ROUTE_LLM_THRESHOLD and not result.spatial_reference_specs:
        return "llm_patch"
    return "merge"


__all__ = ["route_compilation"]
