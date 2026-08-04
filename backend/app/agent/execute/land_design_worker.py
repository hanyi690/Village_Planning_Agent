"""Land Design Worker — deterministic parcel change production for projects/zones/facilities.

Consumes SiteSelectionDecision + LandDesignBrief + SpatialPlanningIntent and
produces a unified ParcelChangeSet. Pure deterministic logic: no LLM, no KG,
no MIP. All geometry mutations delegate to app.modules.spatial_ops.parcel_ops.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple

from shapely.geometry import Point, shape

from app.modules.schema.contracts.classification_ref import ClassificationRef
from app.modules.schema.contracts.parcel_change_contracts import ParcelChange, ParcelChangeSet
from app.modules.schema.contracts.parse_contracts import (
    FacilityTarget,
    ProjectTarget,
    SpatialPlanningIntent,
    ZoneTarget,
)
from app.modules.schema.contracts.selection_contracts import LandDesignBrief, SiteSelectionDecision
from app.modules.spatial_ops.parcel_ops import create_parcel, merge_parcels, reclassify_parcel

DEFAULT_CONSTRUCTION_CODE = "0701"

FACILITY_BUFFER_RADIUS = 0.0002  # degrees, ~20 m at equator


def _geometry_to_wkt(geometry: dict) -> str:
    """Convert a GeoJSON geometry dict to WKT; return "" for invalid geometry."""
    try:
        return shape(geometry).wkt
    except Exception:
        return ""


def _parcel_geometry(parcel: Any) -> dict:
    geometry = getattr(parcel, "geometry", None)
    return geometry if isinstance(geometry, dict) else {}


def _parcel_area_ha(parcel: Any) -> float:
    area_sqm = float(getattr(parcel, "area_sqm", 0) or 0)
    if area_sqm <= 0:
        area_sqm = float(getattr(parcel, "area_ha", 0) or 0) * 10000
    return area_sqm / 10000 if area_sqm > 10000 else area_sqm


def _looks_like_code(value: str) -> bool:
    return bool(value) and any(ch.isdigit() for ch in value)


def _resolve_project_code(brief: Optional[LandDesignBrief]) -> Tuple[str, str]:
    """Resolve (code, name) for a project parcel from its design brief.

    Rule: use a "code:" footprint entry when present; otherwise fall back to
    DEFAULT_CONSTRUCTION_CODE. Callers pass a None brief to signal "no design
    intent" which triggers a preserve action instead.
    """
    if brief is not None:
        for condition in brief.footprint_conditions or []:
            if condition.startswith("code:"):
                code = condition[len("code:") :].strip()
                if code:
                    return code, code
    return DEFAULT_CONSTRUCTION_CODE, DEFAULT_CONSTRUCTION_CODE


def _resolve_zone_code(zone_target: ZoneTarget) -> Tuple[str, str]:
    """Resolve (code, name) for a zone target.

    Rule: use planning_zone when it looks like a code (contains a digit),
    else use land_use; fall back to vne_code when both are empty.
    """
    planning_zone = (zone_target.planning_zone or "").strip()
    land_use = (zone_target.land_use or "").strip()
    vne_code = (zone_target.vne_code or "").strip()
    if _looks_like_code(planning_zone):
        return planning_zone, land_use
    if land_use:
        return land_use, land_use
    return vne_code, land_use


def _classification(code: str, name: str, source: str = "derived") -> ClassificationRef:
    return ClassificationRef(
        system="ghytbm",
        code=code,
        canonical_name=name,
        source=source,
    )


def design_project_parcel(
    project: ProjectTarget,
    brief: Optional[LandDesignBrief],
    selected_bsm: str,
    parcel_by_bsm: Dict[str, Any],
) -> Optional[ParcelChange]:
    """Design parcel changes for a single project.

    Returns None when the selected parcel is not found in parcel_by_bsm
    (the caller skips it). When brief is None, no design intent exists so
    the parcel is preserved with its own dlbm classification.

    Setback-driven split/buffer refinement is a later refinement — this task
    only reclassifies single parcels or merges multi-parcel footprints.
    """
    parcel = parcel_by_bsm.get(str(selected_bsm))
    if parcel is None:
        return None

    if brief is None:
        dlbm = str(getattr(parcel, "dlbm", "") or "")
        return ParcelChange(
            bsm=str(selected_bsm),
            action="preserve",
            derived_from_bsms=[str(selected_bsm)],
            after_classification=_classification(dlbm, "", source="preserve"),
            before_geometry_wkt=_geometry_to_wkt(_parcel_geometry(parcel)),
            after_geometry_wkt=_geometry_to_wkt(_parcel_geometry(parcel)),
            new_area_ha=_parcel_area_ha(parcel),
        )

    new_code, new_name = _resolve_project_code(brief)
    candidate_bsms = list(project.candidate_bsms or [])

    if len(candidate_bsms) > 1:
        source_parcels = [
            parcel_by_bsm[b] for b in candidate_bsms if b in parcel_by_bsm
        ]
        result = merge_parcels(
            source_parcels, new_code, f"MERGED_{'_'.join(candidate_bsms)}"
        )
        if result is None:
            return None
        before_wkt = (
            _geometry_to_wkt(_parcel_geometry(source_parcels[0]))
            if source_parcels
            else ""
        )
        action = "merge"
    else:
        result = reclassify_parcel(parcel, new_code, new_name)
        before_wkt = _geometry_to_wkt(_parcel_geometry(parcel))
        action = "reclassify"

    after_geom = {}
    try:
        after_geom = json.loads(result.get("geometry", ""))
    except Exception:
        after_geom = {}

    return ParcelChange(
        bsm=str(result.get("bsm", selected_bsm)),
        action=action,
        derived_from_bsms=list(result.get("derived_from_bsms") or []),
        after_classification=_classification(new_code, new_name),
        before_geometry_wkt=before_wkt,
        after_geometry_wkt=_geometry_to_wkt(after_geom),
        new_area_ha=float(result.get("area_ha", 0.0) or 0.0),
    )


def design_zone_parcel(
    zone_target: ZoneTarget,
    parcel_by_bsm: Dict[str, Any],
) -> List[ParcelChange]:
    """Reclassify every candidate parcel of a zone target to the zone's land use."""
    code, name = _resolve_zone_code(zone_target)
    changes: List[ParcelChange] = []
    for bsm in zone_target.candidate_bsms or []:
        parcel = parcel_by_bsm.get(str(bsm))
        if parcel is None:
            continue
        result = reclassify_parcel(parcel, code, name)
        changes.append(
            ParcelChange(
                bsm=str(bsm),
                action="reclassify",
                derived_from_bsms=[str(bsm)],
                after_classification=_classification(code, name),
                before_geometry_wkt=_geometry_to_wkt(_parcel_geometry(parcel)),
                after_geometry_wkt=_geometry_to_wkt(_parcel_geometry(parcel)),
                new_area_ha=float(result.get("area_ha", 0.0) or 0.0),
            )
        )
    return changes


def design_facility_parcel(
    facility_target: FacilityTarget,
    parcel_by_bsm: Dict[str, Any],
    brief: Optional[LandDesignBrief],
) -> Optional[ParcelChange]:
    """Create a small facility footprint parcel from its anchor point.

    Returns None when the facility has no anchor_point (cannot be placed
    deterministically). The footprint is a buffer around the anchor with
    FACILITY_BUFFER_RADIUS degrees (~20 m).
    """
    anchor = facility_target.anchor_point
    if anchor is None:
        return None
    lon, lat = float(anchor[0]), float(anchor[1])
    try:
        buffer_geom = Point(lon, lat).buffer(FACILITY_BUFFER_RADIUS)
        geom_dict = json.loads(json.dumps(buffer_geom.__geo_interface__))
    except Exception:
        return None
    bsm = f"{facility_target.type or 'facility'}_0"
    create_parcel(geom_dict, bsm, facility_target.type or "")
    return ParcelChange(
        bsm=bsm,
        action="create",
        derived_from_bsms=[],
        after_classification=_classification(facility_target.type or "", facility_target.type or ""),
        after_geometry_wkt=_geometry_to_wkt(geom_dict),
        new_area_ha=float(buffer_geom.area / 10000),
    )


def build_parcel_change_set(
    changes: List[ParcelChange],
    *,
    area_conservation_verified: bool = False,
    geometry_validity_verified: bool = False,
) -> ParcelChangeSet:
    """Wrap changes into a ParcelChangeSet.

    Actual verification (area conservation, geometry validity) is later-task
    scope; this only records the flags.
    """
    return ParcelChangeSet(
        changes=list(changes),
        area_conservation_verified=area_conservation_verified,
        geometry_validity_verified=geometry_validity_verified,
    )


def design_all(
    intent: SpatialPlanningIntent,
    site_selection: SiteSelectionDecision,
    briefs: List[LandDesignBrief],
    parcel_by_bsm: Dict[str, Any],
) -> ParcelChangeSet:
    """Produce the full ParcelChangeSet for projects, zones and facilities."""
    projects = list(getattr(intent, "project_targets", None) or [])
    selected = list(getattr(site_selection, "selected_combination", None) or [])
    all_changes: List[ParcelChange] = []

    for i, project in enumerate(projects):
        brief = briefs[i] if i < len(briefs) else None
        bsm = selected[i] if i < len(selected) else None
        if bsm:
            change = design_project_parcel(project, brief, bsm, parcel_by_bsm)
            if change is not None:
                all_changes.append(change)

    for zone_target in getattr(intent, "zone_targets", None) or []:
        all_changes.extend(design_zone_parcel(zone_target, parcel_by_bsm))

    for facility in getattr(intent, "facilities", None) or []:
        change = design_facility_parcel(facility, parcel_by_bsm, None)
        if change is not None:
            all_changes.append(change)

    return build_parcel_change_set(all_changes)


__all__ = [
    "design_project_parcel",
    "design_zone_parcel",
    "design_facility_parcel",
    "build_parcel_change_set",
    "design_all",
]
