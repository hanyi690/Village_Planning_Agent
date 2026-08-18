"""Build typed candidate domains from grounded candidate sites."""

from __future__ import annotations

from collections import OrderedDict

from app.contracts.spatial.grounded_problem import GroundedCandidateDomain
from app.contracts.spatial.grounding_contracts import CandidateSite
from app.domain.ground.candidate_identity import candidate_id_for_site


_CANDIDATE_ONLY_ROLES = frozenset(
    {"anchor_geometry", "corridor_candidate", "parcel_candidate", "scope_geometry"}
)


def is_grounding_candidate(candidate: CandidateSite) -> bool:
    """Return whether a candidate has usable typed geometry for SELECT.

    Exact point/line references are valid candidates even when they do not
    resolve to a positive-area parcel.  Scope and corridor geometries remain
    candidate-only and cannot be treated as final execution geometry because
    ``CandidateGeometry.is_executable`` only accepts the execution role.
    """

    geometry = candidate.geometry
    return bool(geometry is not None and geometry.wkt and geometry.kind != "unknown")


def candidate_domain_status(candidate: CandidateSite) -> str:
    geometry = candidate.geometry
    if geometry is None or not geometry.wkt or geometry.kind == "unknown":
        return "unresolved"
    pending_constraint_check = geometry.hard_constraint_status == "pending"
    if geometry.is_executable and (
        geometry.hard_constraint_status == "passed" or pending_constraint_check
    ):
        return "resolved"
    if geometry.is_executable:
        return "candidate_only"
    if geometry.role in _CANDIDATE_ONLY_ROLES:
        return "candidate_only"
    return "ambiguous"


def build_candidate_domains(
    candidates: list[CandidateSite],
) -> list[GroundedCandidateDomain]:
    """Group typed candidates by target while preserving deterministic order."""

    grouped: OrderedDict[str, GroundedCandidateDomain] = OrderedDict()
    for candidate in candidates:
        target_id = str(candidate.target_ref or "")
        if not target_id or not is_grounding_candidate(candidate):
            continue
        candidate_id = candidate_id_for_site(candidate)
        domain = grouped.setdefault(
            target_id,
            GroundedCandidateDomain(target_id=target_id),
        )
        domain.candidate_ids.append(candidate_id)
        if candidate.geometry is not None:
            domain.candidate_geometry_refs.append(candidate_id)
        status = candidate_domain_status(candidate)
        if status == "resolved":
            domain.status = "resolved"
        elif domain.status != "resolved" and status == "candidate_only":
            domain.status = "candidate_only"
        elif domain.status not in {"resolved", "candidate_only"}:
            domain.status = status

    for domain in grouped.values():
        domain.candidate_ids = list(dict.fromkeys(domain.candidate_ids))
        domain.candidate_geometry_refs = list(dict.fromkeys(domain.candidate_geometry_refs))
    return list(grouped.values())


__all__ = [
    "is_grounding_candidate",
    "candidate_domain_status",
    "build_candidate_domains",
]
