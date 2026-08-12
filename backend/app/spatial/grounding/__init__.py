"""Spatial grounding wrapper re-exporting GroundingResult contracts."""

from .grounding_service import (
    CandidateSite,
    GroundingResult,
    HardConstraintResult,
    SpatialQueryEvidence,
    ground_parcels_in_bbox,
    ground_parcels_near,
    resolve_spatial_reference,
)

__all__ = [
    "CandidateSite",
    "GroundingResult",
    "HardConstraintResult",
    "SpatialQueryEvidence",
    "ground_parcels_in_bbox",
    "ground_parcels_near",
    "resolve_spatial_reference",
]
