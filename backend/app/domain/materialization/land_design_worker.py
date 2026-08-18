"""Land Design Worker — deterministic parcel change production for projects/zones/facilities.

Consumes SiteSelectionDecision + LandDesignBrief + SpatialPlanningIntent and
produces a unified ParcelChangeSet. Pure deterministic logic: no LLM, no KG,
no MIP. All geometry mutations delegate to app.spatial.model.parcel_ops.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple

from shapely.geometry import Point, shape

from app.domain.materialization.classification_utils import _classification_from_decision
from app.contracts.artifacts.classification_ref import (
    ClassificationRef,
    classification_code_names,
)
from app.contracts.spatial.parcel_change_contracts import ParcelChange, ParcelChangeSet
from app.contracts.spatial.global_zone_allocation_contracts import (
    AuthoritativeZoneParcelAssignment,
)
from app.contracts.workflow.parse_contracts import (
    FacilityTarget,
    SiteAreaTarget,
    SpatialPlanningIntent,
)
from app.contracts.domain.selection_contracts import LandDesignBrief, SiteSelectionDecision
from app.spatial.model.parcel_ops import create_parcel, merge_parcels, reclassify_parcel
from app.spatial.allocation.selection import parse_scale_ha
from app.spatial.model.subdivision import apply_setback, split_for_footprint

FACILITY_BUFFER_RADIUS = 0.0002  # degrees, ~20 m at equator


def _geometry_to_wkt(geometry: dict) -> str:
    """Convert a GeoJSON geometry dict to WKT; return "" for invalid geometry.

    Invalid geometry (e.g. self-intersecting polygons from cadastral input or
    merge/split output) is repaired via buffer(0)/make_valid so the produced
    WKT is always topologically valid. GeometryCollection results are reduced
    to their areal parts (mirrors app/utils/geo_utils.py convention).
    """
    try:
        g = shape(geometry)
        if not g.is_valid:
            from shapely.ops import unary_union
            from shapely.validation import make_valid

            try:
                g = g.buffer(0)
            except Exception:
                g = make_valid(g)
            if g.geom_type == "GeometryCollection":
                areal = [p for p in g.geoms if p.area > 0]
                if not areal:
                    return ""
                g = unary_union(areal) if len(areal) > 1 else areal[0]
        return g.wkt
    except Exception:
        return ""


def _parcel_geometry(parcel: Any) -> dict:
    geometry = parcel.get("geometry") if isinstance(parcel, dict) else getattr(parcel, "geometry", None)
    return geometry if isinstance(geometry, dict) else {}


def _parcel_area_ha(parcel: Any) -> float:
    area_sqm = float(
        (parcel.get("area_sqm", 0) if isinstance(parcel, dict) else getattr(parcel, "area_sqm", 0))
        or 0
    )
    if area_sqm <= 0:
        area_sqm = float(
            (parcel.get("area_ha", 0) if isinstance(parcel, dict) else getattr(parcel, "area_ha", 0))
            or 0
        ) * 10000
    return area_sqm / 10000


def _parcel_classification(
    parcel: Any,
    *,
    source: str,
) -> Optional[ClassificationRef]:
    """Read a parcel's own declared code system; never infer one from the code."""
    system = str(
        (parcel.get("dlbm_system", "") if isinstance(parcel, dict) else getattr(parcel, "dlbm_system", ""))
        or ""
    ).strip()
    code = str(
        (parcel.get("dlbm", "") if isinstance(parcel, dict) else getattr(parcel, "dlbm", ""))
        or ""
    ).strip()
    names = classification_code_names(system) if system else None
    if not code or names is None or code not in names:
        return None
    try:
        return ClassificationRef(
            system=system,
            code=code,
            canonical_name=names[code],
            source=source,
            evidence_refs=[f"parcel:{code}"],
        )
    except ValueError:
        return None


def design_project_parcel(
    project: SiteAreaTarget,
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
        preserved = _parcel_classification(parcel, source="preserve")
        if preserved is None:
            return None
        return ParcelChange(
            bsm=str(selected_bsm),
            action="preserve",
            derived_from_bsms=[str(selected_bsm)],
            after_classification=preserved,
            before_geometry_wkt=_geometry_to_wkt(_parcel_geometry(parcel)),
            after_geometry_wkt=_geometry_to_wkt(_parcel_geometry(parcel)),
            new_area_ha=_parcel_area_ha(parcel),
            project_ref=project.site_area_id,
            intervention_id=project.site_area_id,
        )

    planned_classification = _classification_from_decision(
        getattr(project, "classification_decision", None)
        or getattr(brief, "classification_decision", None)
    )
    if planned_classification is None:
        return None
    new_code = planned_classification.code
    new_name = planned_classification.canonical_name
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
        after_classification=planned_classification,
        before_geometry_wkt=before_wkt,
        after_geometry_wkt=_geometry_to_wkt(after_geom),
        new_area_ha=float(result.get("area_ha", 0.0) or 0.0),
        project_ref=project.site_area_id,
        intervention_id=project.site_area_id,
    )


def design_project_footprint(
    project: SiteAreaTarget,
    brief: Optional[LandDesignBrief],
    selected_bsm: str,
    parcel_by_bsm: Dict[str, Any],
) -> List[ParcelChange]:
    """Design real project footprints for a project (merge/setback/split).

    Unlike ``design_project_parcel`` (whole-parcel reclassification only), this
    produces an actual footprint geometry when the source parcel is much larger
    than the project's target area.

    Split decision (tolerance = ``brief.area_tolerance_pct``/100, default 5%):
      * ``target_ha`` is None            -> single reclassify/merge (no scale to meet)
      * parcel area < target_ha         -> single change (below-target still places)
      * parcel area within tolerance    -> single change (already fits)
      * parcel area > target*(1+tol)    -> split_for_footprint: one "create"
                                           footprint + "preserve" remainder(s)

    Areas use the same convention as app.spatial.model.subdivision
    (polygon area / 10000 -> ha), so the decision and the split stay consistent.
    Returns ``[]`` when the selected parcel is missing or geometry is unusable.
    """
    parcel = parcel_by_bsm.get(str(selected_bsm))
    if parcel is None:
        return []

    if brief is None:
        change = design_project_parcel(project, None, selected_bsm, parcel_by_bsm)
        return [change] if change is not None else []

    planned_classification = _classification_from_decision(
        getattr(project, "classification_decision", None)
        or getattr(brief, "classification_decision", None)
    )
    if planned_classification is None:
        return []
    new_code = planned_classification.code
    candidate_bsms = list(project.candidate_bsms or [])

    source_geom = None
    source_bsms = [str(selected_bsm)]
    if len(candidate_bsms) > 1:
        source_parcels = [
            parcel_by_bsm[b] for b in candidate_bsms if b in parcel_by_bsm
        ]
        merged = merge_parcels(
            source_parcels, new_code, f"MERGED_{'_'.join(candidate_bsms)}"
        )
        if merged is not None:
            try:
                merged_geom = shape(json.loads(merged.get("geometry", "")))
            except Exception:
                merged_geom = None
            if merged_geom is not None and not merged_geom.is_empty:
                source_geom = merged_geom
                source_bsms = list(merged.get("derived_from_bsms") or source_bsms)
    if source_geom is None:
        try:
            source_geom = shape(_parcel_geometry(parcel))
        except Exception:
            source_geom = None
    if source_geom is None or source_geom.is_empty:
        return []

    target_ha = project.area_ha
    if target_ha is None:
        target_ha = parse_scale_ha(project.scale_text)

    if brief.setback_requirements:
        match = re.search(r"(\d+(?:\.\d+)?)", brief.setback_requirements[0])
        if match:
            setback_m = float(match.group(1))
            if setback_m > 0:
                setback_geom = apply_setback(source_geom, setback_m)
                if setback_geom is not None and not setback_geom.is_empty and setback_geom.area > 0:
                    source_geom = setback_geom

    tolerance = brief.area_tolerance_pct / 100.0
    area_ha = source_geom.area / 10000.0

    def _single_change() -> List[ParcelChange]:
        change = design_project_parcel(project, brief, selected_bsm, parcel_by_bsm)
        if change is None:
            return []
        change.project_ref = project.site_area_id
        change.intervention_id = project.site_area_id
        return [change]

    if target_ha is None or target_ha <= 0:
        return _single_change()
    if area_ha < target_ha:
        return _single_change()
    if abs(area_ha - target_ha) / target_ha <= tolerance:
        return _single_change()
    if area_ha <= target_ha * (1.0 + tolerance):
        return _single_change()

    try:
        footprint, remainders = split_for_footprint(
            source_geom, target_ha, brief.area_tolerance_pct
        )
    except ValueError:
        return _single_change()
    if footprint is None or footprint.is_empty or footprint.area <= 0:
        return _single_change()

    source_wkt = source_geom.wkt
    changes = [
        ParcelChange(
            bsm=f"{project.site_area_id}_FP",
            action="create",
            derived_from_bsms=list(source_bsms),
            after_classification=planned_classification,
            before_geometry_wkt=source_wkt,
            after_geometry_wkt=footprint.wkt,
            new_area_ha=footprint.area / 10000.0,
            project_ref=project.site_area_id,
            intervention_id=project.site_area_id,
        )
    ]
    for i, remainder in enumerate(remainders):
        changes.append(
            ParcelChange(
                bsm=f"{project.site_area_id}_REM_{i}",
                action="preserve",
                derived_from_bsms=list(source_bsms),
                before_geometry_wkt=source_wkt,
                after_geometry_wkt=remainder.wkt,
                new_area_ha=remainder.area / 10000.0,
                project_ref=project.site_area_id,
                intervention_id=project.site_area_id,
            )
        )
    return changes


def design_zone_parcel(
    assignment: AuthoritativeZoneParcelAssignment,
    parcel_by_bsm: Dict[str, Any],
) -> List[ParcelChange]:
    """Materialize exactly one authoritative allocator assignment.

    ZoneTarget candidates are deliberately not accepted here.  Site selection,
    conflict resolution, and parcel ownership must already be represented by
    ``AuthoritativeZoneParcelAssignment``.
    """
    if not isinstance(assignment, AuthoritativeZoneParcelAssignment):
        return []
    bsm = str(assignment.bsm)
    parcel = parcel_by_bsm.get(bsm)
    if parcel is None:
        return []
    names = classification_code_names(assignment.classification_system)
    if names is None or assignment.classification_code not in names:
        return []
    actual_area_ha = _parcel_area_ha(parcel)
    tolerance = max(1e-6, assignment.area_ha * 0.01)
    if actual_area_ha <= 0 or abs(actual_area_ha - assignment.area_ha) > tolerance:
        return []
    geometry_wkt = _geometry_to_wkt(_parcel_geometry(parcel))
    if not geometry_wkt:
        return []
    evidence_refs = sorted(set(
        assignment.lineage.classification_evidence_refs
        + assignment.lineage.candidate_provenance_refs
        + assignment.lineage.parcel_provenance_refs
    ))
    try:
        classification = ClassificationRef(
            system=assignment.classification_system,
            code=assignment.classification_code,
            canonical_name=names[assignment.classification_code],
            source="derived",
            evidence_refs=evidence_refs,
            decision_ref=assignment.lineage.lineage_id,
        )
    except ValueError:
        return []
    result = reclassify_parcel(
        parcel,
        classification.code,
        classification.canonical_name,
    )
    return [
        ParcelChange(
            bsm=bsm,
            action="reclassify",
            derived_from_bsms=[bsm],
            after_classification=classification,
            before_geometry_wkt=geometry_wkt,
            after_geometry_wkt=geometry_wkt,
            new_area_ha=float(result.get("area_ha", actual_area_ha) or actual_area_ha),
            project_ref=assignment.target_id,
            intervention_id=assignment.target_id,
        )
    ]


def design_facility_parcel(
    facility_target: FacilityTarget,
    parcel_by_bsm: Dict[str, Any],
    brief: Optional[LandDesignBrief],
) -> Optional[ParcelChange]:
    """Place a facility on an existing parcel or create a small buffer footprint.

    Returns None when the facility has no anchor_point (cannot be placed
    deterministically). When exactly one parcel contains the anchor point, the
    facility footprint is that parcel (reclassify, no new geometry). Otherwise a
    circular buffer around the anchor is created; its radius is the facility's
    ``service_radius`` (metres, converted via ~111 320 m/deg) when set, else the
    module-level ``FACILITY_BUFFER_RADIUS`` (~20 m).
    """
    anchor = facility_target.anchor_point
    if anchor is None:
        return None
    lon, lat = float(anchor[0]), float(anchor[1])
    anchor_pt = Point(lon, lat)

    containing: List[Tuple[str, Any]] = []
    for bsm, parcel in (parcel_by_bsm or {}).items():
        try:
            geom = shape(_parcel_geometry(parcel))
        except Exception:
            continue
        if geom.is_empty:
            continue
        if geom.contains(anchor_pt):
            containing.append((str(bsm), parcel, geom))
    if len(containing) == 1:
        bsm, parcel, parcel_geom = containing[0]
        facility_classification = _classification_from_decision(
            getattr(facility_target, "classification_decision", None)
        )
        if facility_classification is None:
            return None
        return ParcelChange(
            bsm=bsm,
            action="reclassify",
            derived_from_bsms=[bsm],
            after_classification=facility_classification,
            before_geometry_wkt=parcel_geom.wkt,
            after_geometry_wkt=parcel_geom.wkt,
            new_area_ha=parcel_geom.area / 10000.0,
            intervention_id=facility_target.source_project_id or facility_target.type,
        )

    radius = FACILITY_BUFFER_RADIUS
    if facility_target.service_radius:
        radius = facility_target.service_radius / 111320.0
    try:
        buffer_geom = anchor_pt.buffer(radius)
        geom_dict = json.loads(json.dumps(buffer_geom.__geo_interface__))
    except Exception:
        return None
    bsm = f"{facility_target.type or 'facility'}_0"
    facility_classification = _classification_from_decision(
        getattr(facility_target, "classification_decision", None)
    )
    if facility_classification is None:
        return None
    code = facility_classification.code
    create_parcel(geom_dict, bsm, code)
    return ParcelChange(
        bsm=bsm,
        action="create",
        derived_from_bsms=[],
        after_classification=facility_classification,
        after_geometry_wkt=_geometry_to_wkt(geom_dict),
        new_area_ha=float(buffer_geom.area / 10000),
        intervention_id=facility_target.source_project_id or facility_target.type,
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
    *,
    zone_assignments: List[AuthoritativeZoneParcelAssignment] | None = None,
) -> ParcelChangeSet:
    """Produce changes without deriving zone ownership from intent candidates."""
    projects = list(getattr(intent, "site_area_targets", None) or [])
    selected = list(getattr(site_selection, "selected_combination", None) or [])
    all_changes: List[ParcelChange] = []

    for i, project in enumerate(projects):
        brief = briefs[i] if i < len(briefs) else None
        bsm = selected[i] if i < len(selected) else None
        if bsm:
            all_changes.extend(
                design_project_footprint(project, brief, bsm, parcel_by_bsm)
            )

    for assignment in zone_assignments or []:
        all_changes.extend(design_zone_parcel(assignment, parcel_by_bsm))

    for facility in getattr(intent, "facilities", None) or []:
        change = design_facility_parcel(facility, parcel_by_bsm, None)
        if change is not None:
            all_changes.append(change)

    return build_parcel_change_set(all_changes)


__all__ = [
    "design_project_parcel",
    "design_project_footprint",
    "design_zone_parcel",
    "design_facility_parcel",
    "build_parcel_change_set",
    "design_all",
]
