"""Stable identity helpers for grounded candidate geometries."""

from __future__ import annotations

from app.contracts.ground.candidate_geometry import CandidateGeometry
from app.contracts.ground.grounding_contracts import CandidateSite


def candidate_id_for_geometry(geometry: CandidateGeometry) -> str:
    """Return the canonical candidate id owned by ``CandidateGeometry``."""

    if geometry.candidate_id:
        return geometry.candidate_id
    return CandidateGeometry.model_validate(geometry.model_dump()).candidate_id


def candidate_id_for_site(candidate: CandidateSite) -> str:
    """Return the identity owned by a grounded candidate geometry."""

    if candidate.geometry is None:
        raise ValueError("grounded candidate geometry is required for candidate identity")
    return candidate_id_for_geometry(candidate.geometry)


__all__ = ["candidate_id_for_geometry", "candidate_id_for_site"]
