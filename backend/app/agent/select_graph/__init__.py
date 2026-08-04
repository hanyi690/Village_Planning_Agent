"""SELECT subgraph — candidate parcel ranking and selection.

Consumes GROUND's GroundingResult and exposes an adapter from CandidateSite
(source_parcels) to the legacy CandidateParcel that SELECT scoring consumes.
"""

from __future__ import annotations

from .adapter import candidate_site_to_parcels, grounding_to_candidate_parcels

__all__ = ["candidate_site_to_parcels", "grounding_to_candidate_parcels"]
