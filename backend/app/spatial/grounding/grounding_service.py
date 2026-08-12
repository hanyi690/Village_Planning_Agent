"""Spatial grounding wrapper for the typed workspace."""

from __future__ import annotations

from typing import Any

from app.contracts.spatial.grounding_contracts import (
    CandidateSite,
    GroundingResult,
    HardConstraintResult,
    SpatialQueryEvidence,
)

from app.spatial.model.workspace import SpatialWorkspace


def ground_parcels_in_bbox(workspace: SpatialWorkspace, bbox: tuple[float, float, float, float]) -> list[str]:
    from app.spatial.grounding.grounding import query_parcels_in_bbox

    return query_parcels_in_bbox(workspace.current_parcels(), bbox)


def ground_parcels_near(
    workspace: SpatialWorkspace,
    center: tuple[float, float],
    max_distance_m: float = 500,
) -> list[str]:
    from app.spatial.grounding.grounding import query_parcels_near_entity

    return query_parcels_near_entity(workspace.current_parcels(), center, max_distance_m=max_distance_m)


def resolve_spatial_reference(desc: str, workspace: SpatialWorkspace, **kwargs: Any) -> Any:
    from app.spatial.grounding.grounding import resolve_spatial_description

    bundle = getattr(workspace, "_bundle", None)
    if bundle is None:
        raise ValueError("resolve_spatial_reference requires a workspace materialized from a bundle")
    return resolve_spatial_description(desc, bundle, **kwargs)


__all__ = [
    "CandidateSite",
    "GroundingResult",
    "HardConstraintResult",
    "SpatialQueryEvidence",
    "ground_parcels_in_bbox",
    "ground_parcels_near",
    "resolve_spatial_reference",
]
