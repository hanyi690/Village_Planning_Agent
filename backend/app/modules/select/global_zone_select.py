"""Adapter from GROUND/Suitability facts to authoritative global zone allocation.

The adapter does not invent candidates.  Every parcel in the optimization
model must be target-bound by GROUND and represented by a SuitabilitySurface
candidate.  Parcel geometry remains in the SpatialWorkspace; only stable
bundle references are carried into the allocation artifact.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from app.contracts.select.global_zone_allocation_contracts import (
    GlobalZoneAllocationProblem,
    GlobalZoneAllocationResult,
    ParcelConstraint,
    ZoneCandidateSet,
    ZoneOverlayTargetRef,
    ZoneParcelCandidate,
    ZoneParcelFact,
)
from app.modules.l2.suitability_model import SuitabilitySurface
from app.modules.select.global_zone_parcel_allocator import (
    allocate_global_zone_parcels,
)
from app.core.common.constraint_codes import PROHIBITED_LAND_CONSTRAINTS


_OVERLAY_ROLES = {
    "functional_overlay",
    "protection_overlay",
    "restoration_overlay",
}


def _value(item: Any, name: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(name, default)
    return getattr(item, name, default)


def _parcel_provenance_refs(parcel: Any) -> list[str]:
    bsm = str(_value(parcel, "bsm", "") or "")
    refs = [f"bundle:landuse_current:{bsm}"]
    mapping = _value(parcel, "mapping_provenance", {}) or {}
    if mapping:
        digest = hashlib.sha256(
            json.dumps(mapping, ensure_ascii=False, sort_keys=True, default=str).encode()
        ).hexdigest()
        refs.append(f"parcel-mapping:{digest}")
    return refs


def _parcel_constraints(context: Any, parcel: Any) -> list[ParcelConstraint]:
    index = getattr(context, "constraint_index", None)
    geometry = _value(parcel, "geometry", None)
    if index is None or not geometry:
        return []
    constraints: list[ParcelConstraint] = []
    for overlap in index.geometry_in_constraint(geometry) or []:
        code = str(_value(overlap, "constraint_type", "") or "")
        if not code:
            continue
        constraints.append(
            ParcelConstraint(
                code=code,
                blocks_land_use_assignment=code in PROHIBITED_LAND_CONSTRAINTS,
                provenance_refs=[
                    f"constraint-index:{code}:{str(_value(parcel, 'bsm', '') or '')}"
                ],
            )
        )
    return sorted(constraints, key=lambda item: item.code)


def _candidate_breakdown(candidate: Any, bsm: str) -> dict[str, float]:
    by_parcel = _value(candidate, "parcel_score_breakdowns", {}) or {}
    raw = by_parcel.get(bsm) if isinstance(by_parcel, dict) else None
    if not isinstance(raw, dict):
        raw = _value(candidate, "score_breakdown", {}) or {}
    return {
        str(key): float(value)
        for key, value in dict(raw or {}).items()
        if isinstance(value, (int, float))
    }


def _candidate_score(candidate: Any, bsm: str) -> float:
    by_parcel = _value(candidate, "parcel_scores", {}) or {}
    if isinstance(by_parcel, dict) and bsm in by_parcel:
        return max(0.0, min(1.0, float(by_parcel[bsm])))
    return max(0.0, min(1.0, float(_value(candidate, "score", 0.0) or 0.0)))


def build_global_zone_problem(
    intent: Any,
    suitability: SuitabilitySurface,
    context: Any,
    *,
    provenance_refs: list[str] | None = None,
) -> GlobalZoneAllocationProblem:
    """Build a fail-closed global zone problem from target-bound evidence."""

    zone_targets = list(_value(intent, "zone_targets", []) or [])
    exclusive_targets = [
        target
        for target in zone_targets
        if str(_value(target, "materialization_role", "land_use_assignment"))
        == "land_use_assignment"
    ]
    overlay_sources = [
        *[
            target
            for target in zone_targets
            if str(_value(target, "materialization_role", "")) in _OVERLAY_ROLES
        ],
        *[
            target
            for target in list(_value(intent, "site_area_targets", []) or [])
            if str(_value(target, "materialization_role", "")) in _OVERLAY_ROLES
        ],
    ]

    by_target: dict[str, list[Any]] = {}
    for candidate in suitability.candidates:
        target_id = str(_value(candidate, "target_id", "") or "")
        if target_id:
            by_target.setdefault(target_id, []).append(candidate)

    candidate_sets: list[ZoneCandidateSet] = []
    used_bsms: set[str] = set()
    for target in exclusive_targets:
        target_id = str(_value(target, "target_id", "") or "")
        candidates: dict[str, ZoneParcelCandidate] = {}
        for candidate in by_target.get(target_id, []):
            for raw_bsm in list(_value(candidate, "source_parcels", []) or []):
                bsm = str(raw_bsm or "")
                if not bsm:
                    continue
                evidence_refs = sorted(
                    set(
                        list(_value(candidate, "evidence_refs", []) or [])
                        + [f"suitability:{str(_value(candidate, 'candidate_id', '') or '')}:{bsm}"]
                    )
                )
                candidates[bsm] = ZoneParcelCandidate(
                    bsm=bsm,
                    suitability_score=_candidate_score(candidate, bsm),
                    score_breakdown=_candidate_breakdown(candidate, bsm),
                    hard_feasible=bool(_value(candidate, "hard_feasible", False)),
                    exclusion_codes=list(_value(candidate, "exclusion_reasons", []) or []),
                    provenance_refs=evidence_refs,
                )
                used_bsms.add(bsm)
        candidate_sets.append(
            ZoneCandidateSet(
                target_id=target_id,
                candidates=sorted(candidates.values(), key=lambda item: item.bsm),
            )
        )

    workspace = getattr(context, "workspace", None)
    parcel_by_bsm = {
        str(_value(parcel, "bsm", "") or ""): parcel
        for parcel in (
            (workspace.polygons.get("landuse_current") or [])
            if workspace is not None
            else []
        )
    }
    parcels: list[ZoneParcelFact] = []
    for bsm in sorted(used_bsms):
        parcel = parcel_by_bsm.get(bsm)
        area_ha = float(_value(parcel, "area_sqm", 0.0) or 0.0) / 10000.0 if parcel else 0.0
        if parcel is None or area_ha <= 0 or not _value(parcel, "geometry", None):
            continue
        parcels.append(
            ZoneParcelFact(
                bsm=bsm,
                area_ha=area_ha,
                geometry_ref=f"bundle:landuse_current:{bsm}",
                provenance_refs=_parcel_provenance_refs(parcel),
                constraints=_parcel_constraints(context, parcel),
            )
        )

    overlays = [
        ZoneOverlayTargetRef(
            target_id=str(_value(target, "target_id", "") or ""),
            materialization_role=str(_value(target, "materialization_role", "")),
            candidate_bsms=sorted(
                {
                    str(bsm)
                    for candidate in by_target.get(
                        str(_value(target, "target_id", "") or ""), []
                    )
                    for bsm in list(_value(candidate, "source_parcels", []) or [])
                    if str(bsm)
                }
            ),
            provenance_refs=sorted(
                {
                    ref
                    for candidate in by_target.get(
                        str(_value(target, "target_id", "") or ""), []
                    )
                    for ref in list(_value(candidate, "evidence_refs", []) or [])
                }
            )
            or [f"grounding:{str(_value(target, 'target_id', '') or '')}"],
        )
        for target in overlay_sources
        if str(_value(target, "target_id", "") or "")
    ]
    return GlobalZoneAllocationProblem(
        targets=exclusive_targets,
        candidate_sets=candidate_sets,
        parcels=parcels,
        overlay_targets=overlays,
        provenance_refs=sorted(set(provenance_refs or [])),
    )


def allocate_zones_for_select(
    intent: Any,
    suitability: SuitabilitySurface,
    context: Any,
    *,
    provenance_refs: list[str] | None = None,
) -> GlobalZoneAllocationResult:
    problem = build_global_zone_problem(
        intent,
        suitability,
        context,
        provenance_refs=provenance_refs,
    )
    if not problem.targets:
        return GlobalZoneAllocationResult(
            status="OPTIMAL",
            feasible=True,
            complete=True,
            overlay_targets=problem.overlay_targets,
            input_provenance_refs=problem.provenance_refs,
        )
    return allocate_global_zone_parcels(problem)


__all__ = ["allocate_zones_for_select", "build_global_zone_problem"]
