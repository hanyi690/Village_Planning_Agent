"""Stable identity helpers for grounded candidate geometries."""

from __future__ import annotations

from app.contracts.spatial.candidate_geometry import CandidateGeometry
from app.contracts.spatial.grounding_contracts import CandidateSite


def candidate_id_for_geometry(geometry: CandidateGeometry) -> str:
    """Return the canonical candidate id owned by ``CandidateGeometry``."""

    if geometry.candidate_id:
        return geometry.candidate_id
    return CandidateGeometry.model_validate(geometry.model_dump()).candidate_id


def candidate_id_for_site(candidate: CandidateSite) -> str:
    """Return a geometry-backed id, preserving the legacy site id as fallback."""

    if candidate.geometry is not None:
        return candidate_id_for_geometry(candidate.geometry)
    return candidate.candidate_id or candidate.site_id


__all__ = ["candidate_id_for_geometry", "candidate_id_for_site"]
