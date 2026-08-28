"""Land Design Worker — deterministic parcel change production for projects/zones/facilities.

Consumes typed target/assignment inputs and produces deterministic parcel
changes. Pure logic: no LLM, no KG, no MIP. All geometry mutations delegate to
app.spatial.model.parcel_ops.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from shapely.geometry import Point, shape

from app.modules.execute.classification_utils import _classification_from_decision
from app.contracts.artifacts.classification_ref import (
    ClassificationRef,
    classification_code_names,
)
from app.contracts.execute.parcel_change_contracts import ParcelChange, ParcelChangeSet
from app.contracts.target_projection.parse_contracts import (
    FacilityTarget,
    SiteAreaTarget,
)
from app.contracts.execute.materialization_contracts import LandDesignBrief
from app.spatial.model.parcel_ops import create_parcel, merge_parcels, reclassify_parcel
from app.modules.select.selection import parse_scale_ha
from app.spatial.model.subdivision import apply_setback, split_for_footprint

FACILITY_BUFFER_RADIUS = 0.0002  # degrees, ~20 m at equator


def _first_decimal(text: str) -> float | None:
    """Read the first explicit decimal token without a text-pattern parser."""
    token = ""
    decimal_seen = False
    for char in str(text or ""):
        if char.isdigit():
            token += char
            continue
        if char == "." and token and not decimal_seen:
            decimal_seen = True
            token += char
            continue
        if token:
            break
    if not token or token == ".":
        return None
    try:
        return float(token)
    except ValueError:
        return None


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
        setback_m = _first_decimal(brief.setback_requirements[0])
        if setback_m is not None:
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


def design_facility_parcel(
    facility_target: FacilityTarget,
) -> Optional[ParcelChange]:
    """Create a facility footprint around the authoritative facility anchor.

    The source parcel index is intentionally not used to expand a point anchor
    into a whole BSM.  A facility is a local planning footprint and therefore
    gets an explicit buffer geometry; a later parcel split/overlay stage may
    intersect that footprint with cadastral parcels.
    """
    anchor = facility_target.anchor_point
    if anchor is None:
        return None
    lon, lat = float(anchor[0]), float(anchor[1])
    anchor_pt = Point(lon, lat)

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


__all__ = [
    "design_project_parcel",
    "design_project_footprint",
    "design_facility_parcel",
    "build_parcel_change_set",
]
