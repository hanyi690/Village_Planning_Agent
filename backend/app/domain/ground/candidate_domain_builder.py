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
        geometries_by_id = {
            candidate_id_for_site(candidate): candidate.geometry
            for candidate in candidates
            if str(candidate.target_ref or "") == domain.target_id
            and is_grounding_candidate(candidate)
            and candidate.geometry is not None
        }
        binding_refs = sorted({
            str(getattr(geometry, "source_binding_ref", "") or "")
            for geometry in geometries_by_id.values()
            if str(getattr(geometry, "source_binding_ref", "") or "").strip()
        })
        if len(binding_refs) == 1:
            domain.binding_ref = binding_refs[0]
        required_source_members = [
            geometries_by_id[candidate_id]
            for candidate_id in domain.candidate_ids
            if candidate_id in geometries_by_id
            and geometries_by_id[candidate_id].candidate_membership == "required_member"
        ]
        if (
            len(required_source_members) == len(domain.candidate_ids)
            and len(domain.candidate_ids) > 1
        ):
            domain.selection_mode = "all_members"
            domain.min_selected = len(domain.candidate_ids)
            domain.max_selected = len(domain.candidate_ids)
        else:
            domain.selection_mode = "choose_one"
            domain.min_selected = 1 if domain.candidate_ids else 0
            domain.max_selected = 1 if domain.candidate_ids else 0
    return list(grouped.values())


__all__ = [
    "is_grounding_candidate",
    "candidate_domain_status",
    "build_candidate_domains",
]
