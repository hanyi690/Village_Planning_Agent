"""Project SELECT parcel-level suitability into scenario candidate geometry.

GROUND intentionally keeps recall candidates at evidence granularity.  SELECT
already evaluates each source BSM separately in ``SuitabilitySurface``; this
module makes that refined catalog the single candidate input for the relation
solver and lets EXECUTE reconstruct the same geometry by stable candidate ID.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from app.contracts.spatial.candidate_geometry import CandidateGeometry
from app.contracts.spatial.grounded_problem import (
    GroundedCandidateDomain,
    GroundedPlanningProblem,
)


_POLYGON_OUTPUTS = frozenset({"polygon", "parcel"})
_CONSTRAINT_TOKENS = frozenset({
    "constraint", "farmland", "ecological", "historical", "hazard",
})


def _value(item: Any, name: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(name, default)
    return getattr(item, name, default)


def _geometry_kind(wkt_text: str) -> str:
    try:
        from shapely import wkt

        kind = str(wkt.loads(wkt_text).geom_type).lower()
    except Exception:
        return "unknown"
    if kind in {"point", "multipoint"}:
        return "point"
    if kind in {"linestring", "multilinestring"}:
        return "line"
    if kind in {"polygon", "multipolygon"}:
        return "polygon"
    return "unknown"


def _status(candidate: Any) -> str:
    if bool(_value(candidate, "hard_feasible", False)):
        return "passed"
    reasons = [str(item).lower() for item in (_value(candidate, "exclusion_reasons", None) or [])]
    if any(any(token in reason for token in _CONSTRAINT_TOKENS) for reason in reasons):
        return "failed"
    return "deferred"


def _source_geometry(
    target_id: str,
    bsm: str,
    sources: list[CandidateGeometry],
) -> CandidateGeometry | None:
    matches = [
        source for source in sources
        if str(source.target_id) == target_id and bsm in set(source.source_bsms)
    ]
    if not matches:
        return None
    # Prefer the least coarse and most executable source when several GROUND
    # specs mention the same parcel.
    return sorted(
        matches,
        key=lambda item: (
            bool(item.uncertainty_reason),
            item.role != "execution_geometry",
            item.candidate_id,
        ),
    )[0]


def build_refined_candidate_catalog(
    problem: GroundedPlanningProblem | None,
    suitability_surface: Any = None,
) -> dict[str, CandidateGeometry]:
    """Return original plus SELECT-refined candidate geometry by stable ID."""
    if problem is None:
        return {}
    catalog = {
        str(item.candidate_id): item
        for item in list(problem.candidate_geometries or [])
        if str(item.candidate_id)
    }
    source_geometries = list(problem.candidate_geometries or [])
    target_meta = {
        str(item.target_id): item
        for item in list(problem.target_domains or [])
    }
    for candidate in list(_value(suitability_surface, "candidates", None) or []):
        target_id = str(_value(candidate, "target_id", "") or "")
        bsm_values = [str(item) for item in (_value(candidate, "source_parcels", None) or []) if str(item)]
        wkt_text = str(_value(candidate, "available_geometry_wkt", "") or "")
        if not target_id or len(bsm_values) != 1 or not wkt_text:
            continue
        source = _source_geometry(target_id, bsm_values[0], source_geometries)
        if source is None:
            continue
        kind = _geometry_kind(wkt_text)
        if kind == "unknown":
            continue
        domain = target_meta.get(target_id)
        expected = str(_value(domain, "expected_output_kind", "") or "") if domain else ""
        coarse = bool(source.uncertainty_reason) or source.role in {
            "scope_geometry", "corridor_candidate"
        }
        hard_constraint_status = _status(candidate)
        may_execute = hard_constraint_status == "passed" and not coarse
        if kind == "polygon" and expected in _POLYGON_OUTPUTS and may_execute:
            role = "execution_geometry"
        elif kind == "line" and expected == "line" and may_execute:
            role = "execution_geometry"
        elif kind == "point" and expected == "point" and may_execute:
            role = "execution_geometry"
        elif kind == "line":
            role = "corridor_candidate"
        else:
            role = "parcel_candidate"
        materialization_role = str(source.materialization_role or "")
        source_domain_kind = str(
            getattr(source, "spatial_domain_kind", "") or "unknown"
        )
        if source_domain_kind == "unknown":
            source_domain_kind = "parcel_set" if len(bsm_values) > 1 else "parcel_extent"
        # The refined geometry is the planning domain.  Never keep the source
        # parcel bbox here: a large BSM may contain a much smaller selected
        # footprint, and relation/road workers use this bbox for candidate
        # recall before they materialize the WKT from the candidate catalog.
        try:
            candidate_bbox = tuple(float(value) for value in wkt.loads(wkt_text).bounds)
        except Exception:
            candidate_bbox = None
        source_area_ha = getattr(source, "source_area_ha", None)
        if source_area_ha is None:
            source_area_ha = _value(candidate, "source_area_ha", None)
        planning_area_ha = _value(candidate, "available_area_ha", None)
        coverage_ratio = None
        if source_area_ha and planning_area_ha is not None:
            coverage_ratio = max(
                0.0,
                min(1.0, float(planning_area_ha) / float(source_area_ha)),
            )
        refined = CandidateGeometry(
            target_id=target_id,
            kind=kind,
            role=role,
            materialization_role=materialization_role,
            wkt=wkt_text,
            crs=str(
                _value(candidate, "geometry_crs", "")
                or getattr(source, "crs", "")
                or "EPSG:4326"
            ),
            granularity=(
                "exact_feature"
                if kind in {"point", "line"}
                else (
                    source.granularity
                    if source.granularity in {
                        "parcel_extent", "parcel_set", "settlement", "village_scope", "bbox", "corridor"
                    }
                    else "parcel_set"
                )
            ),
            spatial_domain_kind=source_domain_kind,
            candidate_bbox=candidate_bbox,
            source_area_ha=source_area_ha,
            planning_area_ha=(
                float(planning_area_ha)
                if planning_area_ha is not None
                else None
            ),
            coverage_ratio=coverage_ratio,
            source_ref=str(_value(candidate, "feature_ref", "") or source.source_ref),
            source_refs=list(dict.fromkeys([
                *source.source_refs,
                str(_value(candidate, "feature_ref", "") or ""),
            ])),
            evidence_refs=list(dict.fromkeys([
                *source.evidence_refs,
                *list(_value(candidate, "evidence_refs", None) or []),
            ])),
            confidence=max(float(source.confidence or 0.0), float(_value(candidate, "score", 0.0) or 0.0)),
            uncertainty_radius_m=source.uncertainty_radius_m,
            uncertainty_reason=source.uncertainty_reason,
            source_bsms=bsm_values,
            feature_bsms=list(source.feature_bsms or []),
            source_feature_ids=list(source.source_feature_ids or []),
            entity_refs=list(source.entity_refs or []),
            relation_refs=list(source.relation_refs or []),
            l1_fact_refs=list(source.l1_fact_refs or []),
            l1_snapshot_ref=str(source.l1_snapshot_ref or ""),
            bundle_snapshot_digest=str(source.bundle_snapshot_digest or ""),
            subgeometry_operation=str(
                _value(candidate, "geometry_operation", "")
                or "bundle_extent"
            ),
            subgeometry_diagnostics=list(
                _value(candidate, "geometry_diagnostics", None) or []
            ),
            generation_operation=(
                "select_planning_subgeometry"
                if str(_value(candidate, "geometry_operation", "") or "")
                not in {"", "bundle_extent"}
                else "select_parcel_refinement"
            ),
            hard_constraint_status=hard_constraint_status,
            suitability_components=dict(_value(candidate, "score_breakdown", None) or {}),
        )
        catalog[refined.candidate_id] = refined
    return catalog


def refine_grounded_problem(
    problem: GroundedPlanningProblem | None,
    suitability_surface: Any = None,
) -> GroundedPlanningProblem | None:
    """Append parcel-level alternatives without deleting GROUND evidence."""
    if problem is None:
        return None
    catalog = build_refined_candidate_catalog(problem, suitability_surface)
    original_ids = {str(item.candidate_id) for item in problem.candidate_geometries}
    refined_ids = [key for key in catalog if key not in original_ids]
    if not refined_ids:
        return problem
    ids_by_target: dict[str, list[str]] = defaultdict(list)
    for item in catalog.values():
        if item.candidate_id in refined_ids:
            ids_by_target[str(item.target_id)].append(item.candidate_id)
    domains: list[GroundedCandidateDomain] = []
    for domain in problem.candidate_domains:
        target_id = str(domain.target_id)
        additions = sorted(ids_by_target.get(target_id, []))
        candidate_ids = list(dict.fromkeys([*domain.candidate_ids, *additions]))
        refs = list(dict.fromkeys([*domain.candidate_geometry_refs, *additions]))
        status = domain.status
        if any(
            catalog[candidate_id].is_executable
            and catalog[candidate_id].hard_constraint_status == "passed"
            for candidate_id in additions
        ):
            status = "resolved"
        elif additions and status != "resolved":
            status = "candidate_only"
        domains.append(domain.model_copy(update={
            "candidate_ids": candidate_ids,
            "candidate_geometry_refs": refs,
            "status": status,
        }))
    payload = problem.model_dump(mode="python")
    payload["candidate_geometries"] = list(catalog.values())
    payload["candidate_domains"] = domains
    payload["fingerprint"] = ""
    return GroundedPlanningProblem.model_validate(payload)


__all__ = ["build_refined_candidate_catalog", "refine_grounded_problem"]
