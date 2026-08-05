"""PuLP MIP global zone allocator - EXECUTE zone-synthesis integration boundary.

Pure module (``typing`` + optional ``pulp``).  Given per-zone area targets and
candidate parcel lists, solve a global assignment MIP so that every parcel is
assigned to at most one zone and every zone's assigned area stays within its
target.  Parcels that cannot be assigned (or are blacklisted) are reported as
``unassigned_bsms`` instead of raising.

Candidate entries may be plain bsm strings, mappings (``{"bsm": ..., "area_ha":
...}``) or objects exposing ``bsm`` / ``area_ha`` / ``area_sqm``.  Area lookup
follows the ``land_design_worker._parcel_area_ha`` convention, with a
``metadata["parcel_by_bsm"]`` map as fallback.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from app.modules.ports.zone_allocator import ZoneAllocatorPort
from app.modules.schema.contracts.execution_plan_contracts import (
    ZoneAllocationSolution,
    ZoneAssignmentEntry,
)

_PRESERVE_KINDS = ("preserve", "blacklist", "restricted")


def _parcel_area_ha(parcel: Any) -> float:
    area_sqm = float(getattr(parcel, "area_sqm", 0) or 0)  # getattr intentional: accepts mappings/objects/strings
    if area_sqm <= 0:
        area_sqm = float(getattr(parcel, "area_ha", 0) or 0) * 10000  # getattr intentional: heterogeneous input
    return area_sqm / 10000 if area_sqm > 10000 else area_sqm


def _as_bsm(item: Any) -> str:
    if isinstance(item, str):
        return item
    if isinstance(item, Mapping):
        return str(item.get("bsm") or item.get("id") or "")
    return str(getattr(item, "bsm", None) or "")  # getattr intentional: heterogeneous input


def _entry_area_ha(item: Any, parcel_by_bsm: Mapping[str, Any]) -> float:
    if isinstance(item, Mapping):
        value = item.get("area_ha")
        if value not in (None, ""):
            return float(value)
        value = item.get("area_sqm")
        if value not in (None, ""):
            return float(value) / 10000.0
    else:
        value = getattr(item, "area_ha", None)  # getattr intentional: heterogeneous input
        if value not in (None, ""):
            return float(value)
        value = getattr(item, "area_sqm", None)  # getattr intentional: heterogeneous input
        if value not in (None, ""):
            return float(value) / 10000.0
    parcel = parcel_by_bsm.get(_as_bsm(item))
    if parcel is not None:
        return _parcel_area_ha(parcel)
    return 0.0


def _blacklisted_bsms(constraints: Optional[Sequence[Any]]) -> set[str]:
    blocked: set[str] = set()
    for constraint in constraints or []:
        if isinstance(constraint, Mapping):
            kind = str(constraint.get("type") or constraint.get("kind") or "")
            if kind in _PRESERVE_KINDS:
                for bsm in constraint.get("bsms") or constraint.get("items") or []:
                    blocked.add(_as_bsm(bsm))
        else:
            kind = getattr(constraint, "type", None) or getattr(constraint, "kind", None)
            if kind in _PRESERVE_KINDS:
                for bsm in getattr(constraint, "bsms", None) or getattr(constraint, "items", None) or []:
                    blocked.add(_as_bsm(bsm))
    return blocked


def allocate_zones(
    targets: Mapping[str, float],
    candidates: Mapping[str, Sequence[Any]],
    constraints: Optional[Sequence[Any]] = None,
    metadata: Optional[Mapping[str, Any]] = None,
) -> ZoneAllocationSolution:
    """Solve the global zone allocation MIP.

    Returns a ``ZoneAllocationSolution``; never raises on infeasibility.
    """
    targets = dict(targets or {})
    candidates = {str(zone): list(items) for zone, items in (candidates or {}).items()}
    metadata = dict(metadata or {})
    parcel_by_bsm = metadata.get("parcel_by_bsm") or {}
    blocked = _blacklisted_bsms(constraints)

    diagnostics: List[str] = []
    if not targets or not candidates:
        diagnostics.append("No zone targets or candidates provided")
        return ZoneAllocationSolution(feasible=False, diagnostics=diagnostics)

    try:
        import pulp
    except ImportError:
        diagnostics.append("pulp is not installed; zone allocation skipped")
        return ZoneAllocationSolution(feasible=False, diagnostics=diagnostics)

    area: Dict[Tuple[str, str], float] = {}
    candidate_bsms: Dict[str, set[str]] = {}
    for zone, items in candidates.items():
        if zone not in targets or targets[zone] <= 0:
            continue
        for item in items:
            bsm = _as_bsm(item)
            if not bsm:
                continue
            candidate_bsms.setdefault(zone, set()).add(bsm)
            area[(zone, bsm)] = _entry_area_ha(item, parcel_by_bsm)

    zone_order = [zone for zone in targets if zone in candidate_bsms]
    if not zone_order:
        diagnostics.append("No zone has usable candidate parcels")
        return ZoneAllocationSolution(feasible=False, diagnostics=diagnostics)

    bsm_zones: Dict[str, list[str]] = {}
    for zone, bsms in candidate_bsms.items():
        for bsm in bsms:
            bsm_zones.setdefault(bsm, []).append(zone)

    prob = pulp.LpProblem("global_zone_allocation", pulp.LpMaximize)
    x: Dict[Tuple[str, str], Any] = {}
    for zone in zone_order:
        for bsm in candidate_bsms[zone]:
            x[(zone, bsm)] = pulp.LpVariable(f"x_{zone}_{bsm}", cat=pulp.LpBinary)

    # Objective: maximise total assigned area.
    prob += pulp.lpSum(
        area[(zone, bsm)] * x[(zone, bsm)]
        for zone in zone_order
        for bsm in candidate_bsms[zone]
        if bsm not in blocked
    )

    # Each parcel to at most one zone.
    for bsm, zones in bsm_zones.items():
        prob += pulp.lpSum(x[(zone, bsm)] for zone in zones if (zone, bsm) in x) <= 1

    # Each zone within its target area.
    for zone in zone_order:
        prob += (
            pulp.lpSum(
                area[(zone, bsm)] * x[(zone, bsm)]
                for bsm in candidate_bsms[zone]
                if bsm not in blocked
            )
            <= targets[zone]
        )

    # Preserved parcels cannot be assigned.
    for bsm in blocked:
        if bsm in bsm_zones:
            prob += (
                pulp.lpSum(x[(zone, bsm)] for zone in bsm_zones[bsm] if (zone, bsm) in x)
                == 0
            )

    prob.solve(pulp.PULP_CBC_CMD(msg=0))
    status = pulp.LpStatus[prob.status]
    if status != "Optimal":
        diagnostics.append(f"Solver status: {status}")
        return ZoneAllocationSolution(feasible=False, diagnostics=diagnostics)

    assignments: List[ZoneAssignmentEntry] = []
    assigned_bsms: set[str] = set()
    objective = float(pulp.value(prob.objective) or 0.0)
    for zone in zone_order:
        zone_meta = metadata.get(zone)
        land_use = ""
        if isinstance(zone_meta, Mapping):
            land_use = str(
                zone_meta.get("land_use")
                or zone_meta.get("category_name_zh")
                or zone_meta.get("zone_name")
                or ""
            )
        for bsm in candidate_bsms[zone]:
            variable = x[(zone, bsm)]
            if variable.value() is not None and variable.value() > 0.5:
                assignments.append(
                    ZoneAssignmentEntry(
                        bsm=bsm,
                        zone_id=zone,
                        land_use=land_use,
                        area_ha=round(area[(zone, bsm)], 4),
                        source="allocator",
                    )
                )
                assigned_bsms.add(bsm)

    all_bsms = set(bsm_zones)
    unassigned = sorted(all_bsms - assigned_bsms)
    diagnostics.append(
        f"Assigned {len(assignments)} parcels across {len(zone_order)} zones"
    )
    return ZoneAllocationSolution(
        assignments=assignments,
        unassigned_bsms=unassigned,
        objective_value=round(objective, 4),
        feasible=True,
        diagnostics=diagnostics,
    )


class PuLPZoneAllocator:
    """ZoneAllocatorPort implementation backed by the pure ``allocate_zones``."""

    def allocate(
        self,
        targets: dict,
        candidates: dict,
        constraints: Optional[Sequence[Any]] = None,
        metadata: Optional[Mapping[str, Any]] = None,
    ) -> ZoneAllocationSolution:
        return allocate_zones(targets, candidates, constraints=constraints, metadata=metadata)


__all__ = ["PuLPZoneAllocator", "allocate_zones"]
