"""SELECT adapter for global project/facility/point site allocation."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from shapely.geometry import shape

from app.contracts.spatial.global_site_allocation_contracts import (
    GlobalSiteAllocationProblem,
    GlobalSiteAllocationResult,
    SiteCandidateEvidence,
    SiteParcelCapacity,
    SiteTargetDemand,
)
from app.domain.suitability.model import SuitabilitySurface
from app.spatial.allocation.global_site_allocator import allocate_global_sites


_OVERLAY_ROLES = {
    "functional_overlay",
    "protection_overlay",
    "restoration_overlay",
}


def _value(item: Any, name: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(name, default)
    return getattr(item, name, default)


def _target_binding(target: Any) -> dict[str, Any]:
    if hasattr(target, "model_dump"):
        return target.model_dump(mode="json")
    if isinstance(target, dict):
        return dict(target)
    return {
        key: value
        for key, value in vars(target).items()
        if not key.startswith("_")
    }


def _required_area_m2(target: Any) -> float:
    footprint = _value(target, "footprint_area_m2", None)
    if footprint is not None:
        return max(float(footprint), 0.0)
    area_ha = _value(target, "area_ha", None)
    if area_ha is not None:
        return max(float(area_ha) * 10_000.0, 0.0)
    return 0.0


def _priority(target: Any) -> tuple[int, str]:
    explicit = _value(target, "allocation_priority", None)
    if explicit is None:
        explicit = _value(target, "priority", None)
    if isinstance(explicit, (int, float)) and not isinstance(explicit, bool):
        return max(1, min(100, int(explicit))), "typed_target_priority"
    phase = str(
        _value(target, "implementation_phase", "")
        or _value(target, "phase", "")
    ).lower()
    if phase in {"short", "medium", "long"}:
        return {"short": 80, "medium": 50, "long": 20}[phase], "implementation_phase"
    return 50, "equal_default"


def _target_refs(target: Any) -> list[str]:
    refs = [
        *(str(item) for item in (_value(target, "claim_refs", []) or []) if str(item)),
        str(_value(target, "source_instruction_id", "") or ""),
        str(_value(target, "source_report_key", "") or ""),
    ]
    return sorted(set(item for item in refs if item))


def _non_zone_targets(intent: Any) -> list[SiteTargetDemand]:
    demands: list[SiteTargetDemand] = []
    for target_type, field_name in (
        ("project", "project_targets"),
        ("facility", "facilities"),
    ):
        for target in list(_value(intent, field_name, []) or []):
            if not bool(_value(target, "requires_spatial", True)):
                continue
            if str(_value(target, "materialization_role", "") or "") in _OVERLAY_ROLES:
                continue
            output_kind = str(_value(target, "expected_output_kind", "") or "")
            if output_kind not in {"point", "parcel", "polygon"}:
                continue
            target_id = str(_value(target, "target_id", "") or "")
            if not target_id:
                continue
            priority, priority_source = _priority(target)
            binding = _target_binding(target)
            exclusive = output_kind in {"parcel", "polygon"}
            binding["allocation_exclusive_bsm"] = exclusive
            demands.append(SiteTargetDemand(
                target_id=target_id,
                target_type=target_type,
                expected_output_kind=output_kind,
                required_area_m2=_required_area_m2(target),
                priority=priority,
                priority_source=priority_source,
                exclusive_bsm=exclusive,
                target_binding=binding,
                provenance_refs=_target_refs(target),
            ))
    return sorted(demands, key=lambda item: item.target_id)


def _parcel_refs(parcel: Any) -> list[str]:
    bsm = str(_value(parcel, "bsm", "") or "")
    refs = [f"bundle:landuse_current:{bsm}"]
    mapping = _value(parcel, "mapping_provenance", {}) or {}
    if mapping:
        digest = hashlib.sha256(
            json.dumps(mapping, ensure_ascii=False, sort_keys=True, default=str).encode()
        ).hexdigest()
        refs.append(f"parcel-mapping:{digest}")
    return refs


def _anchor(parcel: Any) -> tuple[float, float] | None:
    try:
        geometry = shape(_value(parcel, "geometry", None) or {})
    except Exception:
        return None
    if geometry.is_empty or not geometry.is_valid:
        return None
    point = geometry.representative_point()
    return float(point.x), float(point.y)


def build_global_site_problem(
    intent: Any,
    suitability: SuitabilitySurface,
    context: Any,
    *,
    provenance_refs: list[str] | None = None,
) -> GlobalSiteAllocationProblem:
    """Build a target-bound global problem without full-pool fallback."""

    targets = _non_zone_targets(intent)
    targets_by_id = {item.target_id: item for item in targets}
    target_objects = {
        str(_value(target, "target_id", "") or ""): target
        for field in ("project_targets", "facilities")
        for target in list(_value(intent, field, []) or [])
    }
    workspace = getattr(context, "workspace", None)
    parcel_by_bsm = {
        str(_value(parcel, "bsm", "") or ""): parcel
        for parcel in (
            (workspace.polygons.get("landuse_current") or [])
            if workspace is not None
            else []
        )
    }

    candidates: list[SiteCandidateEvidence] = []
    used_bsms: set[str] = set()
    seen: set[tuple[str, str]] = set()
    for row in sorted(suitability.candidates, key=lambda item: (item.target_id, item.candidate_id)):
        target_id = str(_value(row, "target_id", "") or "")
        if target_id not in targets_by_id:
            continue
        target = target_objects.get(target_id)
        explicit_bsms = set(_value(target, "candidate_bsms", []) or [])
        excluded_bsms = set(_value(target, "excluded_bsms", []) or [])
        for raw_bsm in list(_value(row, "source_parcels", []) or []):
            bsm = str(raw_bsm or "")
            if not bsm or bsm in excluded_bsms:
                continue
            if explicit_bsms and bsm not in explicit_bsms:
                continue
            key = (target_id, bsm)
            if key in seen:
                continue
            seen.add(key)
            parcel = parcel_by_bsm.get(bsm)
            anchor = _anchor(parcel) if parcel is not None else None
            if anchor is None:
                continue
            evidence_refs = sorted(set([
                *list(_value(row, "evidence_refs", []) or []),
                f"suitability:{str(_value(row, 'candidate_id', '') or '')}",
            ]))
            candidates.append(SiteCandidateEvidence(
                target_id=target_id,
                bsm=bsm,
                candidate_id=str(_value(row, "candidate_id", "") or f"{target_id}:{bsm}"),
                anchor_point=anchor,
                suitability_score=max(0.0, min(1.0, float(_value(row, "score", 0.0) or 0.0))),
                score_breakdown={
                    str(key): float(value)
                    for key, value in dict(_value(row, "score_breakdown", {}) or {}).items()
                    if isinstance(value, (int, float)) and not isinstance(value, bool)
                },
                hard_feasible=bool(_value(row, "hard_feasible", False)),
                exclusion_codes=list(_value(row, "exclusion_reasons", []) or []),
                evidence_refs=evidence_refs,
                availability_diagnostics=list(_value(row, "availability_diagnostics", []) or []),
            ))
            used_bsms.add(bsm)

    parcels: list[SiteParcelCapacity] = []
    for bsm in sorted(used_bsms):
        parcel = parcel_by_bsm.get(bsm)
        area_sqm = float(_value(parcel, "area_sqm", 0.0) or 0.0) if parcel is not None else 0.0
        if parcel is None or area_sqm <= 0 or not _value(parcel, "geometry", None):
            continue
        parcels.append(SiteParcelCapacity(
            bsm=bsm,
            capacity_area_m2=area_sqm,
            geometry_ref=f"bundle:landuse_current:{bsm}",
            provenance_refs=_parcel_refs(parcel),
        ))

    return GlobalSiteAllocationProblem(
        targets=targets,
        candidates=candidates,
        parcels=parcels,
        provenance_refs=sorted(set(provenance_refs or [])),
    )


def allocate_non_zone_for_select(
    intent: Any,
    suitability: SuitabilitySurface,
    context: Any,
    *,
    provenance_refs: list[str] | None = None,
) -> GlobalSiteAllocationResult:
    return allocate_global_sites(build_global_site_problem(
        intent,
        suitability,
        context,
        provenance_refs=provenance_refs,
    ))


__all__ = ["allocate_non_zone_for_select", "build_global_site_problem"]
