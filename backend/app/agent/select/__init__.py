"""SELECT subgraph — candidate parcel ranking and selection.

Consumes GROUND's GroundingResult and exposes an adapter from CandidateSite
(source_parcels) to the legacy CandidateParcel that SELECT scoring consumes.
"""

from __future__ import annotations

from .adapter import candidate_site_to_parcels, grounding_to_candidate_parcels
from .aggregate import (
    build_land_design_brief,
    build_site_selection_decision,
    select_aggregate,
)
from .gate import evaluate_select_gate, select_gate_route
from .review import build_preview_geojson, build_select_review_package

__all__ = [
    "candidate_site_to_parcels",
    "grounding_to_candidate_parcels",
    "select_aggregate",
    "build_site_selection_decision",
    "build_land_design_brief",
    "evaluate_select_gate",
    "select_gate_route",
    "build_select_review_package",
    "build_preview_geojson",
]
