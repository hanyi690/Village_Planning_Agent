"""Project SELECT parcel-level suitability into scenario candidate geometry.

GROUND intentionally keeps recall candidates at evidence granularity.  SELECT
already evaluates each source BSM separately in ``SuitabilitySurface``; this
module makes that refined catalog the single candidate input for the relation
solver and lets EXECUTE reconstruct the same geometry by stable candidate ID.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from shapely import wkt
from shapely.geometry import box

from app.contracts.ground.candidate_geometry import CandidateGeometry
from app.contracts.ground.grounded_problem import (
    GroundedCandidateDomain,
    GroundedPlanningProblem,
    derive_parcel_resource_pool,
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
        target_kind = str(_value(domain, "target_kind", "") or "") if domain else ""
        source_domain_kind = str(
            getattr(source, "spatial_domain_kind", "") or "unknown"
        )
        if source_domain_kind == "unknown":
            source_domain_kind = "parcel_set" if len(bsm_values) > 1 else "parcel_extent"
        uncertainty_reason = str(source.uncertainty_reason or "").lower()
        parcel_level = (
            len(bsm_values) == 1
            and kind == "polygon"
            and source.role not in {"scope_geometry", "corridor_candidate"}
        )
        if parcel_level:
            source_domain_kind = "parcel_extent"
        coarse = (
            any(token in uncertainty_reason for token in ("bbox", "village_scope"))
            or ("coarse" in uncertainty_reason and not parcel_level)
            or source.role in {"scope_geometry", "corridor_candidate"}
            or source_domain_kind in {"bbox", "corridor", "village_scope"}
        )
        hard_constraint_status = _status(candidate)
        may_execute = hard_constraint_status == "passed" and not coarse
        materialized_wkt = wkt_text
        materialized_kind = kind
        generation_operation = "select_parcel_refinement"
        # Facilities are point interventions even when SELECT evaluates a
        # parcel polygon.  Materialize a deterministic point inside the
        # eligible parcel so the downstream single-choice solver receives
        # executable geometry rather than a parcel candidate.
        if kind == "polygon" and expected == "point" and target_kind == "facility" and may_execute:
            try:
                representative = wkt.loads(wkt_text).representative_point()
            except Exception:
                representative = None
            if representative is not None and not representative.is_empty:
                materialized_wkt = representative.wkt
                materialized_kind = "point"
                generation_operation = "select_parcel_representative_point"
        if materialized_kind == "polygon" and expected in _POLYGON_OUTPUTS and may_execute:
            role = "execution_geometry"
        elif materialized_kind == "line" and expected == "line" and may_execute:
            role = "execution_geometry"
        elif materialized_kind == "point" and expected == "point" and may_execute:
            role = "execution_geometry"
        elif materialized_kind == "line":
            role = "corridor_candidate"
        else:
            role = "parcel_candidate"
        materialization_role = str(source.materialization_role or "")
        # The suitability surface is evaluated against the exact source BSM
        # and returns the usable subgeometry for that BSM.  Once a single BSM
        # is selected, the parent GROUND union's coarse uncertainty no longer
        # describes this refined geometry.  Keep the exactness explicit so
        # SELECT does not reject an otherwise source-backed executable member
        # merely because its parent recall geometry was village-coarse.
        refined_uncertainty_reason = (
            "exact_bsm_refinement"
            if parcel_level and hard_constraint_status == "passed"
            else source.uncertainty_reason
        )
        refined_uncertainty_radius = (
            0.0
            if parcel_level and hard_constraint_status == "passed"
            else source.uncertainty_radius_m
        )
        # The refined geometry is the planning domain.  Never keep the source
        # parcel bbox here: a large BSM may contain a much smaller selected
        # footprint, and relation/road workers use this bbox for candidate
        # recall before they materialize the WKT from the candidate catalog.
        try:
            candidate_bbox = tuple(float(value) for value in wkt.loads(materialized_wkt).bounds)
        except Exception:
            candidate_bbox = None
        # Suitability evaluates the exact source BSM geometry.  Prefer that
        # measured area over the coarse GROUND union extent; otherwise a
        # stale recall extent can be smaller than the exact parcel and make a
        # valid eligible area look contradictory at the CandidateGeometry
        # contract boundary.
        measured_source_area_ha = _value(candidate, "source_area_ha", None)
        if measured_source_area_ha is not None and float(measured_source_area_ha) > 0:
            source_area_ha = float(measured_source_area_ha)
        else:
            source_area_ha = getattr(source, "source_area_ha", None)
        planning_area_ha = _value(candidate, "available_area_ha", None)
        availability_status = str(
            _value(candidate, "availability_status", "unknown") or "unknown"
        )
        coverage_ratio = None
        if source_area_ha and planning_area_ha is not None:
            coverage_ratio = max(
                0.0,
                min(1.0, float(planning_area_ha) / float(source_area_ha)),
            )
        eligible_area_ha = _value(candidate, "eligible_area_ha", None)
        if source_area_ha and eligible_area_ha is not None:
            eligible_area_ha = min(
                max(float(eligible_area_ha), 0.0),
                float(source_area_ha),
            )
        excluded_area_ha = _value(candidate, "excluded_area_ha", None)
        if source_area_ha and eligible_area_ha is not None:
            excluded_area_ha = max(
                float(source_area_ha) - float(eligible_area_ha),
                0.0,
            )
        elif excluded_area_ha is not None and source_area_ha:
            excluded_area_ha = min(
                max(float(excluded_area_ha), 0.0),
                float(source_area_ha),
            )
        # A hard exclusion can leave the recall candidate WKT in place for
        # diagnostics, but it cannot retain a positive planning area.  Keep
        # the whole/partial availability distinction explicit instead of
        # constructing the contradictory state
        # ``fully_unavailable + planning_area_ha > 0``.
        if availability_status == "fully_unavailable":
            planning_area_ha = 0.0
            coverage_ratio = 0.0 if source_area_ha else None
            eligible_area_ha = 0.0
            excluded_area_ha = source_area_ha if source_area_ha else None
        elif availability_status == "fully_available":
            # ``fully_available`` is authoritative for the exact source
            # geometry, but metric/CRS rounding can leave a tiny residual in
            # the carried area fields.  Clamp only that numerical residue;
            # a material disagreement is made non-executable instead of
            # silently erasing an excluded subarea.
            residual_tolerance = max(float(source_area_ha or 0.0) * 1e-6, 1e-9)
            if excluded_area_ha is not None and float(excluded_area_ha) > residual_tolerance:
                availability_status = "unknown"
                excluded_area_ha = min(
                    max(float(excluded_area_ha), 0.0),
                    float(source_area_ha),
                ) if source_area_ha else float(excluded_area_ha)
            else:
                excluded_area_ha = 0.0
        refined = CandidateGeometry(
            target_id=target_id,
            physical_project_ref=str(getattr(source, "physical_project_ref", "") or ""),
            component_claim_refs=list(getattr(source, "component_claim_refs", None) or []),
            component_fact_refs=list(getattr(source, "component_fact_refs", None) or []),
            kind=materialized_kind,
            role=role,
            materialization_role=materialization_role,
            wkt=materialized_wkt,
            eligible_geometry_wkt=str(
                _value(candidate, "eligible_geometry_wkt", "") or ""
            ),
            crs=str(
                _value(candidate, "geometry_crs", "")
                or getattr(source, "crs", "")
                or "EPSG:4326"
            ),
            granularity=(
                "exact_feature"
                if materialized_kind in {"point", "line"}
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
            identity_confidence=source.identity_confidence,
            geometry_confidence=source.geometry_confidence,
            suitability_score=(
                float(_value(candidate, "score", 0.0) or 0.0)
                if _value(candidate, "score", None) is not None
                else None
            ),
            uncertainty_radius_m=refined_uncertainty_radius,
            uncertainty_reason=refined_uncertainty_reason,
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
            availability_status=availability_status,
            eligible_area_ha=eligible_area_ha,
            excluded_area_ha=excluded_area_ha,
            adjacent_parcel_bsms=list(
                _value(candidate, "adjacent_parcel_bsms", None) or []
            ),
            adjacency_evidence_refs=list(
                _value(candidate, "adjacency_evidence_refs", None) or []
            ),
            generation_operation=generation_operation,
            hard_constraint_status=hard_constraint_status,
            suitability_components=dict(_value(candidate, "score_breakdown", None) or {}),
        )
        # A persisted SELECT problem is already the frozen candidate authority.
        # In particular, shared-parcel partitioning updates the WKT while
        # retaining the candidate ID for ScenarioSet/approval lineage.  Do
        # not rebuild that ID from the raw suitability parent during EXECUTE,
        # or the partitioned geometry would be silently overwritten.
        if refined.candidate_id not in catalog:
            catalog[refined.candidate_id] = refined
    return catalog


def _cut_polygon_by_area_fraction(geometry: Any, fraction: float) -> tuple[Any, Any] | None:
    """Cut a polygon deterministically without inventing a new source extent.

    The geometry is already source-backed.  This helper only partitions that
    geometry along its widest axis, so shared-resource targets can receive
    disjoint members while the unassigned remainder stays in the source
    parcel.  Area ratios are used only within the existing candidate WKT;
    authoritative metric budgets remain the candidate's frozen planning area.
    """
    if geometry is None or geometry.is_empty or geometry.geom_type not in {"Polygon", "MultiPolygon"}:
        return None
    fraction = max(0.0, min(1.0, float(fraction)))
    if fraction <= 1e-9:
        return geometry.__class__(), geometry
    if fraction >= 1.0 - 1e-9:
        return geometry, geometry.__class__()
    minx, miny, maxx, maxy = geometry.bounds
    span_x = maxx - minx
    span_y = maxy - miny
    if max(span_x, span_y) <= 1e-12:
        return None
    use_x = span_x >= span_y
    low, high = (minx, maxx) if use_x else (miny, maxy)
    pad = max(span_x, span_y, 1.0) * 1e-9
    total_area = float(geometry.area)
    target_area = total_area * fraction
    selected = None
    remainder = None
    for _ in range(48):
        mid = (low + high) / 2.0
        cutter = (
            box(minx - pad, miny - pad, mid, maxy + pad)
            if use_x
            else box(minx - pad, miny - pad, maxx + pad, mid)
        )
        candidate = geometry.intersection(cutter)
        area = float(candidate.area)
        if area < target_area:
            low = mid
        else:
            high = mid
            selected = candidate
    if selected is None:
        return None
    remainder = geometry.difference(selected)
    if selected.is_empty or remainder.is_empty:
        return None
    selected = selected.buffer(0)
    remainder = remainder.buffer(0)
    if selected.is_empty or remainder.is_empty or not selected.is_valid or not remainder.is_valid:
        return None
    return selected, remainder


def _partition_shared_parcel_candidates(
    catalog: dict[str, CandidateGeometry],
    candidate_ids: set[str],
) -> dict[str, CandidateGeometry]:
    """Partition identical source-backed subgeometries for shared BSM targets.

    This is intentionally narrow: it runs only when every target contributes
    exactly one executable site-footprint candidate for a BSM and those
    candidates describe the same source-backed polygon.  Different
    candidate geometries remain alternatives and are left untouched; SELECT
    then fails closed on overlap instead of guessing which constraint should
    win.
    """
    groups: dict[str, list[CandidateGeometry]] = defaultdict(list)
    for candidate_id in sorted(candidate_ids):
        candidate = catalog.get(candidate_id)
        if candidate is None:
            continue
        if (
            candidate.role != "execution_geometry"
            or candidate.materialization_role not in {"site_footprint", "land_use_assignment"}
            or candidate.kind != "polygon"
            or candidate.hard_constraint_status != "passed"
            or len(candidate.source_bsms) != 1
            or candidate.planning_area_ha is None
            or float(candidate.planning_area_ha or 0.0) <= 0
        ):
            continue
        groups[str(candidate.source_bsms[0])].append(candidate)

    for bsm, candidates in groups.items():
        target_ids = {str(item.target_id) for item in candidates}
        if len(candidates) < 2 or len(target_ids) != len(candidates):
            continue
        # Prefer the explicit usable parent extent carried by suitability.
        # ``wkt`` is often already a target-sized footprint, so partitioning
        # that geometry by source-parcel area would under-size every member.
        eligible_wkts = [str(item.eligible_geometry_wkt or "") for item in candidates]
        parent_wkts = eligible_wkts if all(eligible_wkts) else [str(item.wkt or "") for item in candidates]
        try:
            geometries = [wkt.loads(value) for value in parent_wkts]
        except Exception:
            continue
        if any(
            geometry.is_empty
            or not geometry.is_valid
            or geometry.geom_type not in {"Polygon", "MultiPolygon"}
            for geometry in geometries
        ):
            continue
        base = geometries[0]
        # Do not merge target-specific suitability domains.  Auto-partition is
        # safe only when every member came from the same source-backed extent.
        if any(float(base.symmetric_difference(geometry).area) > 1e-12 for geometry in geometries[1:]):
            continue
        source_area = float(candidates[0].source_area_ha or 0.0)
        capacity = min(
            [
                float(item.eligible_area_ha)
                for item in candidates
                if item.eligible_area_ha is not None
            ]
            or [source_area]
        )
        if source_area <= 0 or capacity <= 0:
            continue
        requested = [float(item.planning_area_ha or 0.0) for item in candidates]
        if sum(requested) > capacity + 1e-9:
            continue
        remaining = base
        original_area = float(base.area)
        for candidate, requested_area in zip(candidates, requested):
            fraction = min(1.0, max(0.0, requested_area / capacity))
            if float(remaining.area) <= 1e-12 or fraction <= 1e-9:
                break
            relative_fraction = min(1.0, fraction * original_area / float(remaining.area))
            cut = _cut_polygon_by_area_fraction(remaining, relative_fraction)
            if cut is None:
                break
            piece, remaining = cut
            if piece is None or piece.is_empty or not piece.is_valid:
                break
            catalog[candidate.candidate_id] = candidate.model_copy(update={
                "wkt": piece.wkt,
                "candidate_bbox": tuple(float(value) for value in piece.bounds),
                "subgeometry_operation": "shared_parcel_capacity_partition",
                "subgeometry_diagnostics": [
                    *list(candidate.subgeometry_diagnostics),
                    f"shared_source_bsm:{bsm}",
                    "partitioned_from_eligible_parent_extent" if all(eligible_wkts)
                    else "partitioned_from_identical_candidate_extent",
                ],
            })
        else:
            continue
        # If any member failed to partition, retain the original catalog so
        # the solver can reject the unresolved overlap rather than executing a
        # partial and therefore misleading allocation.
        for candidate in candidates:
            catalog[candidate.candidate_id] = candidate
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
    catalog = _partition_shared_parcel_candidates(catalog, set(refined_ids))
    ids_by_target: dict[str, list[str]] = defaultdict(list)
    for item in catalog.values():
        if item.candidate_id in refined_ids:
            ids_by_target[str(item.target_id)].append(item.candidate_id)
    domains: list[GroundedCandidateDomain] = []
    for domain in problem.candidate_domains:
        target_id = str(domain.target_id)
        additions = sorted(ids_by_target.get(target_id, []))
        executable_additions = [
            candidate_id
            for candidate_id in additions
            if catalog[candidate_id].is_executable
            and catalog[candidate_id].hard_constraint_status == "passed"
        ]
        if executable_additions:
            # Once SELECT has a source-backed parcel refinement, the coarse
            # GROUND union must not remain an equally eligible solver member.
            # Keeping it in ``candidate_geometries`` preserves recall lineage;
            # removing it from the domain prevents a full-parcel geometry from
            # winning over the cut footprint during optimization.
            original_ids = {
                str(item.candidate_id)
                for item in problem.candidate_geometries
                if str(item.target_id or "") == target_id
            }
            candidate_ids = [
                item
                for item in domain.candidate_ids
                if str(item) not in original_ids
            ]
            candidate_ids = list(dict.fromkeys([*candidate_ids, *executable_additions]))
            refs = list(dict.fromkeys([*candidate_ids, *executable_additions]))
        else:
            candidate_ids = list(dict.fromkeys([*domain.candidate_ids, *additions]))
            refs = list(dict.fromkeys([*domain.candidate_geometry_refs, *additions]))
        status = domain.status
        if executable_additions:
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
    active_candidate_ids = {
        str(candidate_id)
        for domain in domains
        for candidate_id in domain.candidate_ids
        if str(candidate_id)
    }
    payload["parcel_resource_pool"] = derive_parcel_resource_pool(
        [
            candidate
            for candidate in catalog.values()
            if str(candidate.candidate_id) in active_candidate_ids
        ],
        pool_id=f"select-parcel-pool:{problem.fingerprint[:16]}",
    )
    # Refinement is a new planning-domain projection.  Recompute the target
    # readiness from the refined geometry instead of retaining GROUND's
    # coarse target status (which may have been ``candidate_only`` for a
    # parcel union or corridor).  Otherwise the solver would fail closed even
    # though SELECT has produced a source-backed executable subgeometry.
    target_domains = []
    for target_domain in list(problem.target_domains or []):
        target_id = str(target_domain.target_id or "")
        target_candidates = [
            item for item in catalog.values()
            if str(item.target_id or "") == target_id
        ]
        executable = [
            item for item in target_candidates
            if item.is_executable and item.hard_constraint_status == "passed"
        ]
        update: dict[str, Any] = {}
        if executable:
            update["status"] = "resolved"
            update["geometry_roles"] = list(dict.fromkeys(
                [*target_domain.geometry_roles, *(item.role for item in executable)]
            ))
            update["candidate_site_refs"] = list(dict.fromkeys(
                [*target_domain.candidate_site_refs, *(item.candidate_id for item in executable)]
            ))
        target_domains.append(target_domain.model_copy(update=update))
    payload["target_domains"] = target_domains
    payload["fingerprint"] = ""
    return GroundedPlanningProblem.model_validate(payload)


__all__ = ["build_refined_candidate_catalog", "refine_grounded_problem"]
