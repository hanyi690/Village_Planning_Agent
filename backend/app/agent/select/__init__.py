"""SELECT subgraph — candidate parcel ranking and selection.

Consumes GROUND's GroundingResult and ranks CandidateSite candidates for
selection. The derived per-parcel CandidateParcel shape is built at the
selection edge (ADR-002); it is not imported across the subgraph boundary.
"""

from __future__ import annotations

from .aggregate import (
    build_land_design_brief,
    build_site_selection_decision,
    select_aggregate,
)
from .gate import evaluate_select_gate, select_gate_route
from .review import build_preview_geojson, build_select_review_package

__all__ = [
    "select_aggregate",
    "build_site_selection_decision",
    "build_land_design_brief",
    "evaluate_select_gate",
    "select_gate_route",
    "build_select_review_package",
    "build_preview_geojson",
]
