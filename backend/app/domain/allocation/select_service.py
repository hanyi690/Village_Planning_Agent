"""SELECT subgraph aggregate - deterministic orchestrator over select_parcel.

Consumes ``GroundingResult`` + ``SpatialPlanningIntent`` + ``PlanningContext``
and produces a ``tuple[SiteSelectionDecision, list[LandDesignBrief]]``.

Pure orchestration: selection is delegated to ``app.spatial.allocation.selection.select_parcel``
per project target with priority-sequential conflict allocation (occupied anchor
points accumulate so a parcel taken by an earlier, higher-priority target is
rejected for later targets). No LLM, no kg imports; given the same inputs the
output is fully deterministic.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional, Tuple

from app.infrastructure.context.planning_context import PlanningContext
from app.contracts.spatial.grounding_contracts import CandidateSite, GroundingResult
from app.contracts.artifacts.classification_ref import classification_code_names
from app.contracts.workflow.parse_contracts import SiteAreaTarget
from app.contracts.artifacts.provenance import Provenance
from app.contracts.domain.selection_contracts import (
    EliminatedCandidate,
    LandDesignBrief,
    RankedCandidate,
    SiteSelectionDecision,
    TargetAssignment,
)
from app.spatial.allocation.facility_location import (
    DemandPoint,
    FacilityCandidate,
    solve_maximal_covering,
)
from app.spatial.allocation.selection import (
    CandidateParcel,
    PlacementDecision,
    ScoredCandidate,
    SelectionTarget,
    select_parcel,
)

logger = logging.getLogger(__name__)

_SCORE_BREAKDOWN_STUBS = {
    "proximity": 0.0,
    "construction": 0.0,
    "area_fit": 0.0,
    "road_access": 0.0,
    "service_coverage": 0.0,
}


def _classification_ready(target: Any) -> bool:
    decision = getattr(target, "classification_decision", None)
    if getattr(target, "expected_output_kind", "") == "point":
        return True
    return decision is not None and getattr(decision, "status", "") == "resolved"


def _road_contract_ready(target: Any) -> tuple[bool, str]:
    """Validate minimum typed road evidence without inventing a catalog hit."""
    from app.contracts.domain.road_planning import (
        ExistingRoadPlanningInput,
        NewCorridorPlanningInput,
    )

    payload = target.model_dump(mode="python") if hasattr(target, "model_dump") else dict(target)
    kind = str(payload.get("road_planning_kind") or "")
    fields = {
        key: payload.get(key)
        for key in (
            "target_id",
            "source_project_id",
            "action",
            "road_level",
            "length_m",
            "roadbed_width_m",
            "pavement_width_m",
            "routing_evidence",
        )
    }
    try:
        if kind == "existing_road_intervention":
            ExistingRoadPlanningInput(
                **fields,
                existing_road_feature_ids=payload.get("existing_road_feature_ids") or [],
                existing_road_segment_ids=payload.get("existing_road_segment_ids") or [],
                road_evidence_refs=payload.get("road_evidence_refs") or [],
            )
        elif kind == "new_corridor":
            NewCorridorPlanningInput(
                **fields,
                start_endpoint=payload.get("start_endpoint"),
                end_endpoint=payload.get("end_endpoint"),
            )
        else:
            return False, "road_planning_kind_unresolved"
    except Exception as exc:
        return False, f"road_contract_unresolved:{type(exc).__name__}"
    return True, ""


def _candidate_site_to_parcels(
    site: CandidateSite, parcel_by_bsm: dict[str, object]
) -> list[CandidateParcel]:
    """Derive one CandidateParcel per source BSM from a CandidateSite.

    CandidateParcel is a computation intermediate built at the selection edge
    (ADR-002); CandidateSite remains the canonical candidate model.
    """
    parcels = []
    for bsm in site.source_parcels:
        parcel = parcel_by_bsm.get(str(bsm))
        if parcel is None:
            continue
        dlbm = str(getattr(parcel, "dlbm", "") or "").strip()
        dlbm_system = str(getattr(parcel, "dlbm_system", "") or "").strip()
        names = classification_code_names(dlbm_system) if dlbm_system else None
        parcels.append(
            CandidateParcel(
                bsm=str(bsm),
                geometry=getattr(parcel, "geometry", {}),
                dlbm=dlbm,
                dlbm_system=dlbm_system,
                dlmc=(names or {}).get(dlbm, ""),
                area_ha=(getattr(parcel, "area_sqm", 0.0) or 0.0) / 10000.0,
                target_ref=(getattr(site, "target_ref", None) or ""),
            )
        )
    return parcels


def _grounding_to_candidate_parcels(
    result: GroundingResult, bundle
) -> list[CandidateParcel]:
    """Derive the per-parcel pool from a GroundingResult at the selection edge."""
    parcel_by_bsm = {}
    for p in (bundle.polygons.get("landuse_current") or []):
        parcel_by_bsm[str(p.bsm)] = p
    parcels = []
    for site in result.candidates:
        parcels.extend(_candidate_site_to_parcels(site, parcel_by_bsm))
    return parcels


def _filter_parcels_for_target(
    parcels: list[CandidateParcel], target_ref: str
) -> list[CandidateParcel]:
    """Keep only parcels explicitly tagged for ``target_ref``."""
    return [p for p in parcels if p.target_ref == target_ref]


def _target_suitability(
    surface: Any,
    target_id: str,
) -> tuple[
    set[str] | None,
    Dict[str, float],
    Dict[str, float],
    Dict[str, float],
]:
    if surface is None:
        return None, {}, {}, {}
    rows = [
        item
        for item in list(getattr(surface, "candidates", None) or [])
        if str(getattr(item, "target_id", "") or "") == target_id
    ]
    if not rows:
        return set(), {}, {}, {}
    feasible: set[str] = set()
    slope_hazard: Dict[str, float] = {}
    road_distance_m: Dict[str, float] = {}
    service_coverage: Dict[str, float] = {}
    for row in rows:
        for bsm in list(getattr(row, "source_parcels", None) or []):
            bsm = str(bsm)
            if getattr(row, "hard_feasible", False):
                feasible.add(bsm)
            breakdown = dict(getattr(row, "score_breakdown", {}) or {})
            value = breakdown.get("slope_hazard")
            if value is not None:
                slope_hazard[bsm] = float(value)
            if breakdown.get("road_distance_m") is not None:
                road_distance_m[bsm] = float(breakdown["road_distance_m"])
            if breakdown.get("service_coverage") is not None:
                service_coverage[bsm] = float(breakdown["service_coverage"])
    return feasible, slope_hazard, road_distance_m, service_coverage


def _breakdown_from_scored(scored: ScoredCandidate) -> Dict[str, float]:
    """Build a 5-key breakdown from a ScoredCandidate's dimension reasons."""
    breakdown = dict(_SCORE_BREAKDOWN_STUBS)
    for reason in scored.reasons:
        label, sep, value = reason.partition(":")
        if sep and label in breakdown:
            try:
                breakdown[label] = float(value)
            except ValueError:
                pass
    return breakdown


def _setback_requirements(decision: PlacementDecision) -> List[str]:
    labels = []
    for rejection in decision.rejected:
        for detail in rejection.detail:
            if detail.startswith("constraint:"):
                labels.extend(detail[len("constraint:"):].split(","))
    return sorted(set(labels))


def build_land_design_brief(
    project: SiteAreaTarget,
    decision: PlacementDecision,
    context: Any,
) -> LandDesignBrief:
    footprint = [f"category:{project.category}"]
    if project.scale_text:
        footprint.append(f"scale:{project.scale_text}")
    access = [f"road:{r}" for r in (project.related_road_targets or [])]
    adjacency = [f"facility:{f}" for f in (project.related_facility_types or [])]
    return LandDesignBrief(
        project_ref=project.target_id,
        classification_decision=project.classification_decision,
        footprint_conditions=footprint,
        access_requirements=access,
        adjacency_requirements=adjacency,
        setback_requirements=_setback_requirements(decision),
        preservation_requirements=[],
        area_tolerance_pct=5.0,
    )


def build_site_selection_decision(
    placements: List[PlacementDecision],
    *,
    run_id: str,
    session_id: str,
    expected_output_kinds: Optional[Dict[str, str]] = None,
) -> SiteSelectionDecision:
    """Aggregate placement decisions into a ``SiteSelectionDecision``.

    Ranked scores come from ``select_parcel``'s per-candidate ranking: the
    winner's real score and 3-dimension breakdown are surfaced; the zero-stub
    ``road_access``/``service_coverage`` dimensions stay 0.0 until external
    network/facility data is wired in.
    """
    assignments: List[TargetAssignment] = []
    expected_output_kinds = expected_output_kinds or {}
    full_ranking: List[RankedCandidate] = []
    eliminated: List[EliminatedCandidate] = []
    best_score_by_target = {}
    placed_count = 0
    rank = 0
    for placement in placements:
        if placement.status == "placed":
            placed_count += 1
            rank += 1
            winner = next(
                (s for s in placement.ranking if s.bsm == placement.selected_bsm),
                None,
            )
            if winner is not None:
                score = winner.score
                breakdown = _breakdown_from_scored(winner)
            else:
                score = placement.selected_score
                breakdown = dict(_SCORE_BREAKDOWN_STUBS)
            best_score_by_target[placement.target_id] = score
            full_ranking.append(
                RankedCandidate(
                    candidate_id=placement.selected_bsm,
                    rank=rank,
                    score=score,
                    score_breakdown=breakdown,
                    project_ref=placement.target_id or None,
                )
            )
            assignments.append(
                TargetAssignment(
                    target_id=placement.target_id,
                    target_type="site_area",
                    status="placed",
                    selected_bsm=placement.selected_bsm,
                    anchor_point=placement.anchor_point,
                    expected_output_kind=expected_output_kinds.get(
                        placement.target_id, "parcel"
                    ),
                    score=score,
                    score_breakdown=breakdown,
                )
            )
        else:
            best_score_by_target[placement.target_id] = 0.0
            assignments.append(
                TargetAssignment(
                    target_id=placement.target_id,
                    target_type="site_area",
                    status="unplaced",
                    expected_output_kind=expected_output_kinds.get(
                        placement.target_id, "parcel"
                    ),
                    reason=placement.reason,
                )
            )
        for rejection in placement.rejected:
            is_occupied = (
                placement.status != "placed"
                and rejection.reason == "hard_filter"
                and any(
                    d.startswith("occupied_proximity") for d in rejection.detail
                )
            )
            if is_occupied:
                eliminated.append(
                    EliminatedCandidate(
                        candidate_id=rejection.bsm,
                        elimination_reason="allocated_to_higher_priority",
                        eliminated_by_constraint="occupied_proximity",
                    )
                )
            else:
                eliminated.append(
                    EliminatedCandidate(
                        candidate_id=rejection.bsm,
                        elimination_reason=(
                            "hard_filter"
                            if rejection.reason == "hard_filter"
                            else rejection.reason
                        ),
                        eliminated_by_constraint=",".join(rejection.detail),
                    )
                )
    decision = SiteSelectionDecision(
        target_assignments=assignments,
        full_ranking=full_ranking,
        eliminated=eliminated,
        decision_factors={
            "target_count": len(placements),
            "placed_count": placed_count,
            "unplaced_count": len(placements) - placed_count,
            "best_score_by_target": best_score_by_target,
        },
        review_status="auto",
        provenance=Provenance(
            source="select_aggregate",
            run_id=run_id,
            module="app.domain.allocation.select_service",
            trace=[f"session:{session_id}"],
            natural_language_description=(
                f"SELECT aggregate for {len(placements)} targets"
            ),
        ),
    )
    return decision


def _cluster_centroid(context: PlanningContext) -> Optional[Tuple[float, float]]:
    anchors = getattr(context, "village_anchors", None) or []
    if not anchors:
        return None
    first = anchors[0]
    if isinstance(first, dict):
        lon = first.get("lon")
        lat = first.get("lat")
        if lon is not None and lat is not None:
            return (float(lon), float(lat))
    return None


def _geometry_centroid(geometry: Dict[str, Any]) -> Optional[Tuple[float, float]]:
    if not geometry:
        return None
    from shapely.geometry import shape

    try:
        geom = shape(geometry)
    except Exception:
        return None
    if geom.is_empty:
        return None
    centroid = geom.centroid
    return (centroid.x, centroid.y)


def _facility_demand_points(context: PlanningContext) -> List[DemandPoint]:
    """Weighted demand points from village anchors, falling back to bundle settlements."""
    demand: List[DemandPoint] = []
    anchors = getattr(context, "village_anchors", None) or []
    for i, anchor in enumerate(anchors):
        if isinstance(anchor, dict):
            lon = anchor.get("lon")
            lat = anchor.get("lat")
        else:
            lon = getattr(anchor, "lon", None)
            lat = getattr(anchor, "lat", None)
        if lon is None or lat is None:
            continue
        demand.append(DemandPoint(id=f"village_{i}", lon=float(lon), lat=float(lat), weight=1.0))
    if demand:
        return demand
    workspace = getattr(context, "workspace", None)
    settlements = []
    if workspace is not None and getattr(workspace, "polygons", None) is not None:
        settlements = workspace.polygons.get("settlement") or []
    for i, s in enumerate(settlements):
        centroid = _geometry_centroid(getattr(s, "geometry", None))
        if centroid is None:
            continue
        demand.append(DemandPoint(id=f"settlement_{i}", lon=centroid[0], lat=centroid[1], weight=1.0))
    return demand


def _place_facility(
    facility: Any,
    parcels: List[CandidateParcel],
    context: PlanningContext,
    cluster_centroid: Optional[Tuple[float, float]],
    occupied: List[Tuple[float, float]],
    filter_cache: Optional[Dict[str, Tuple[Any, List[str]]]] = None,
    suitability_surface: Any = None,
) -> Tuple[PlacementDecision, str]:
    """Place one facility: MCLP when a service radius is known, else select_parcel.

    Mutates ``facility.anchor_point`` in place so the returned intent carries the
    resolved location. Returns the placement decision and the chosen bsm.
    """
    if not facility.candidate_bsms:
        return (
            PlacementDecision(
                target_id=facility.target_id,
                status="unplaced",
                reason="no_target_specific_candidates",
            ),
            "",
        )
    wanted = set(facility.candidate_bsms)
    feasible, slope_hazard, road_distance_m, service_coverage = _target_suitability(
        suitability_surface,
        str(facility.target_id),
    )
    if feasible is not None:
        wanted &= feasible
    pool = [p for p in parcels if p.bsm in wanted]
    facility_candidates: List[FacilityCandidate] = []
    by_bsm: Dict[str, CandidateParcel] = {}
    for p in pool:
        centroid = _geometry_centroid(p.geometry)
        if centroid is None:
            continue
        facility_candidates.append(
            FacilityCandidate(candidate_id=p.bsm, lon=centroid[0], lat=centroid[1])
        )
        by_bsm[p.bsm] = p
    if facility.service_radius is not None and facility_candidates:
        demand = _facility_demand_points(context)
        if demand:
            chosen = solve_maximal_covering(
                facility_candidates,
                demand,
                float(facility.service_radius),
                n_facilities=1,
            )
            if chosen:
                bsm = chosen[0]
                centroid = by_bsm[bsm].geometry and _geometry_centroid(by_bsm[bsm].geometry)
                facility.anchor_point = centroid
                return (
                    PlacementDecision(
                        target_id=facility.target_id,
                        selected_bsm=bsm,
                        anchor_point=centroid,
                        reason=f"mclp:{bsm}",
                        status="placed",
                        selected_score=1.0,
                    ),
                    bsm,
                )
    target = SelectionTarget(
        target_id=facility.target_id,
        name=facility.type,
        category="facility",
        scale_text="",
    )
    decision = select_parcel(
        target,
        candidates=pool,
        constraint_index=context.constraint_index,
        hazards=None,
        occupied=occupied,
        cluster_centroid=cluster_centroid,
        filter_cache=filter_cache,
        slope_hazard=slope_hazard or None,
        road_distance_m=road_distance_m or None,
        service_coverage=service_coverage or None,
        project_type="facility",
    )
    if decision.status == "placed" and decision.anchor_point is not None:
        facility.anchor_point = decision.anchor_point
    return decision, decision.selected_bsm


def select_aggregate(
    result: GroundingResult,
    intent: Any,
    context: PlanningContext,
    suitability_surface: Any = None,
    zone_allocation: Any = None,
    site_allocation: Any = None,
) -> Tuple[SiteSelectionDecision, List[LandDesignBrief]]:
    run_id = getattr(context, "session_id", "") or ""
    if context.workspace is None:
        empty = build_site_selection_decision([], run_id=run_id, session_id=run_id)
        return empty, []
    parcels = _grounding_to_candidate_parcels(result, context.workspace)
    all_projects = list(getattr(intent, "site_area_targets", None) or [])
    all_facilities = list(getattr(intent, "facilities", None) or [])
    if suitability_surface is not None and site_allocation is None:
        from app.domain.allocation.global_site_select import (
            allocate_non_zone_for_select,
        )

        site_allocation = allocate_non_zone_for_select(
            intent,
            suitability_surface,
            context,
        )
    global_site_assignments: list[TargetAssignment] = []
    global_site_placements: list[PlacementDecision] = []
    facility_placements: Dict[str, Dict[str, Any]] = {}
    target_objects = {
        str(getattr(target, "target_id", "") or ""): target
        for target in [*all_projects, *all_facilities]
        if str(getattr(target, "target_id", "") or "")
    }
    if site_allocation is not None:
        for row in list(getattr(site_allocation, "assignments", None) or []):
            target_id = str(getattr(row, "target_id", "") or "")
            target = target_objects.get(target_id)
            assigned = str(getattr(row, "status", "")) == "assigned"
            target_type = str(getattr(row, "target_type", "") or "site_area")
            anchor = getattr(row, "anchor_point", None)
            bsm = str(getattr(row, "bsm", "") or "")
            if target_type == "facility" and target is not None and assigned:
                target.anchor_point = anchor
            lineage = getattr(row, "lineage", None)
            global_site_assignments.append(TargetAssignment(
                target_id=target_id,
                target_type=target_type,
                status="placed" if assigned else "unplaced",
                selected_bsm=bsm if assigned else "",
                anchor_point=anchor if assigned else None,
                expected_output_kind=str(
                    getattr(row, "expected_output_kind", "point")
                ),
                target_binding=dict(getattr(row, "target_binding", {}) or {}),
                reason="" if assigned else str(getattr(row, "reason", "") or "global_site_unplaced"),
                score=float(getattr(row, "score", 0.0) or 0.0),
                score_breakdown=dict(getattr(row, "score_breakdown", {}) or {}),
                allocation_lineage_refs=(
                    [str(getattr(lineage, "lineage_id", ""))]
                    if lineage is not None
                    else []
                ),
            ))
            if target_type == "site_area":
                global_site_placements.append(PlacementDecision(
                    target_id=target_id,
                    selected_bsm=bsm if assigned else "",
                    anchor_point=anchor if assigned else None,
                    status="placed" if assigned else "unplaced",
                    reason="" if assigned else str(getattr(row, "reason", "") or "global_site_unplaced"),
                    selected_score=float(getattr(row, "score", 0.0) or 0.0),
                ))
            elif target_type == "facility":
                facility_placements[target_id] = {
                    "bsm": bsm if assigned else "",
                    "anchor_point": anchor if assigned else None,
                    "status": "placed" if assigned else "unplaced",
                    "facility_type": str(getattr(target, "type", "") or ""),
                }
    projects = (
        [
            project
            for project in all_projects
            if getattr(project, "materialization_role", None) in {
                "functional_overlay",
                "protection_overlay",
                "restoration_overlay",
            }
        ]
        if site_allocation is not None
        else all_projects
    )
    facilities = [] if site_allocation is not None else all_facilities
    cluster_centroid = _cluster_centroid(context)
    occupied: List[Tuple[float, float]] = []
    filter_cache: Dict[str, Tuple[Any, List[str]]] = {}
    placements: List[PlacementDecision] = []
    overlay_assignments: List[TargetAssignment] = []
    _t_projects = time.monotonic()
    for project in projects:
        # L3 may contain non-spatial programme actions (training, service
        # operations, research, etc.). They remain execution tasks but do not
        # require a parcel. Only an explicitly spatial target participates in
        # SELECT; an explicitly spatial target with no grounded pool remains
        # a hard GROUND/SELECT failure.
        if not getattr(project, "requires_spatial", True):
            logger.info(
                "select_aggregate: non-spatial project %s deferred to EXECUTE",
                project.target_id,
            )
            continue
        if getattr(project, "materialization_role", None) in {
            "functional_overlay",
            "protection_overlay",
            "restoration_overlay",
        }:
            overlay_bsms = sorted(
                {
                    str(bsm)
                    for site in list(getattr(result, "candidates", None) or [])
                    if str(getattr(site, "target_ref", "") or "") == project.target_id
                    for bsm in list(getattr(site, "source_parcels", None) or [])
                    if str(bsm)
                }
                - set(getattr(project, "excluded_bsms", None) or [])
            )
            overlay_assignments.append(
                TargetAssignment(
                    target_id=project.target_id,
                    target_type="site_area",
                    status="placed" if overlay_bsms else "unplaced",
                    selected_bsm=overlay_bsms[0] if overlay_bsms else "",
                    selected_bsms=overlay_bsms,
                    expected_output_kind=project.expected_output_kind,
                    target_binding=project.model_dump(mode="json"),
                    reason="" if overlay_bsms else "overlay_grounding_unresolved",
                    allocation_lineage_refs=[
                        f"grounding-overlay:{project.target_id}:{bsm}"
                        for bsm in overlay_bsms
                    ],
                )
            )
            continue
        if (
            str(getattr(project, "expected_output_kind", "")) in {"parcel", "polygon"}
            and not _classification_ready(project)
        ):
            placements.append(
                PlacementDecision(
                    target_id=project.target_id,
                    selected_bsm="",
                    status="unplaced",
                    reason="classification_unresolved",
                )
            )
            continue
        target = SelectionTarget(
            target_id=project.target_id,
            name=project.name,
            category="site_area",
            scale_text=project.scale_text,
        )
        project_pool = _filter_parcels_for_target(parcels, project.target_id)
        excluded_bsms = set(getattr(project, "excluded_bsms", None) or [])
        if excluded_bsms:
            project_pool = [parcel for parcel in project_pool if parcel.bsm not in excluded_bsms]
        feasible_bsms, slope_hazard, road_distance_m, service_coverage = _target_suitability(
            suitability_surface,
            project.target_id,
        )
        if feasible_bsms is not None:
            project_pool = [p for p in project_pool if p.bsm in feasible_bsms]
        if not project_pool:
            logger.warning(
                "select_aggregate: no candidates for project %s; marking unplaced for human review",
                project.target_id,
            )
            placements.append(
                PlacementDecision(
                    target_id=project.target_id,
                    selected_bsm="",
                    status="unplaced",
                    reason="no_project_candidates",
                )
            )
            continue
        placement = select_parcel(
            target,
            candidates=project_pool,
            constraint_index=context.constraint_index,
            hazards=None,
            occupied=occupied,
            cluster_centroid=cluster_centroid,
            filter_cache=filter_cache,
            slope_hazard=slope_hazard or None,
            road_distance_m=road_distance_m or None,
            service_coverage=service_coverage or None,
            project_type=str(getattr(project, "category", "") or "default"),
        )
        if placement.status == "placed" and placement.anchor_point is not None:
            occupied.append(placement.anchor_point)
        placements.append(placement)
    logger.info(
        "select_aggregate: projects loop %.2fs (projects=%d placed=%d)",
        time.monotonic() - _t_projects, len(projects),
        len([p for p in placements if p.status == "placed"]),
    )
    _t_facilities = time.monotonic()
    decision = build_site_selection_decision(
        placements,
        run_id=run_id,
        session_id=run_id,
        expected_output_kinds={
            str(project.target_id): str(project.expected_output_kind)
            for project in projects
        },
    )
    decision.target_assignments.extend(overlay_assignments)
    decision.target_assignments.extend(global_site_assignments)
    placements.extend(global_site_placements)
    # Backfill facility candidate_bsms from grounding candidate sites so
    # placement honours the grounded direction (e.g. 南部) instead of falling
    # back to the global pool (which collapses all facilities onto one parcel).
    candidate_sites = list(getattr(result, "candidates", None) or [])
    for facility in facilities:
        if getattr(facility, "candidate_bsms", None):
            continue
        fac_id = getattr(facility, "target_id", "") or ""
        for site in candidate_sites:
            if getattr(site, "target_ref", None) == fac_id:
                site_bsms = list(getattr(site, "source_parcels", None) or [])
                if site_bsms:
                    facility.candidate_bsms = site_bsms
                break
    # Backfill zone candidate_bsms from grounding candidate sites so the
    # zone worker reclassifies the grounded parcels instead of an empty set.
    zone_targets_all = list(getattr(intent, "zone_targets", None) or [])
    for zone in zone_targets_all:
        if getattr(zone, "candidate_bsms", None):
            continue
        zone_id = getattr(zone, "target_id", "") or ""
        for site in candidate_sites:
            if getattr(site, "target_ref", None) == zone_id:
                site_bsms = list(getattr(site, "source_parcels", None) or [])
                if site_bsms:
                    zone.candidate_bsms = site_bsms
                break
    facility_rank = len(placements) + 1
    for i, facility in enumerate(facilities):
        if not _classification_ready(facility):
            decision.target_assignments.append(
                TargetAssignment(
                    target_id=facility.target_id,
                    target_type="facility",
                    status="unplaced",
                    anchor_point=facility.anchor_point,
                    expected_output_kind=facility.expected_output_kind,
                    target_binding=facility.model_dump(mode="json"),
                    reason="classification_unresolved",
                )
            )
            facility_placements[facility.target_id] = {
                "bsm": "",
                "anchor_point": facility.anchor_point,
                "status": "unplaced",
                "facility_type": facility.type,
            }
            continue
        decision_p, bsm = _place_facility(
            facility,
            parcels,
            context,
            cluster_centroid,
            occupied,
            filter_cache,
            suitability_surface,
        )
        if decision_p.status == "placed":
            decision.target_assignments.append(
                TargetAssignment(
                    target_id=facility.target_id,
                    target_type="facility",
                    status="placed",
                    selected_bsm=bsm,
                    anchor_point=facility.anchor_point,
                    expected_output_kind=facility.expected_output_kind,
                    target_binding=facility.model_dump(mode="json"),
                    score=decision_p.selected_score,
                    score_breakdown=dict(_SCORE_BREAKDOWN_STUBS),
                )
            )
            facility_rank += 1
            if facility.anchor_point is not None:
                occupied.append(facility.anchor_point)
            facility_placements[facility.target_id] = {
                "bsm": bsm,
                "anchor_point": facility.anchor_point,
                "status": "placed",
                "facility_type": facility.type,
            }
        else:
            decision.target_assignments.append(
                TargetAssignment(
                    target_id=facility.target_id,
                    target_type="facility",
                    status="unplaced",
                    anchor_point=facility.anchor_point,
                    expected_output_kind=facility.expected_output_kind,
                    target_binding=facility.model_dump(mode="json"),
                    reason=decision_p.reason,
                )
            )
            facility_placements[facility.target_id] = {
                "bsm": "",
                "anchor_point": facility.anchor_point,
                "status": "unplaced",
                "facility_type": facility.type,
            }
    if facilities:
        decision.decision_factors["facility_count"] = len(facilities)
        decision.decision_factors["facility_placements"] = facility_placements
    elif all_facilities and site_allocation is not None:
        decision.decision_factors["facility_count"] = len(all_facilities)
        decision.decision_factors["facility_placements"] = facility_placements
    decision.decision_factors["global_site_allocation"] = {
        "status": str(getattr(site_allocation, "status", "missing")),
        "complete": bool(getattr(site_allocation, "complete", False)),
        "assignment_count": len(
            list(getattr(site_allocation, "assignments", None) or [])
        ),
        "diagnostic_codes": [
            str(getattr(item, "code", ""))
            for item in list(getattr(site_allocation, "diagnostics", None) or [])
        ],
    }
    logger.info(
        "select_aggregate: facilities loop %.2fs (facilities=%d)",
        time.monotonic() - _t_facilities, len(facilities),
    )
    _t_zones = time.monotonic()
    assigned_ids = {assignment.target_id for assignment in decision.target_assignments}
    zone_rows = list(getattr(zone_allocation, "assignments", None) or [])
    zone_rows_by_target: Dict[str, List[Any]] = {}
    for row in zone_rows:
        zone_rows_by_target.setdefault(str(getattr(row, "target_id", "") or ""), []).append(row)
    zone_balances = {
        str(getattr(item, "target_id", "") or ""): item
        for item in list(getattr(zone_allocation, "area_balances", None) or [])
    }
    allocation_ready = bool(
        zone_allocation is not None
        and getattr(zone_allocation, "status", "") == "OPTIMAL"
        and getattr(zone_allocation, "complete", False)
    )
    for zone in list(getattr(intent, "zone_targets", None) or []):
        target_id = str(getattr(zone, "target_id", "") or "")
        if not target_id or target_id in assigned_ids:
            continue
        rows = sorted(zone_rows_by_target.get(target_id, []), key=lambda item: item.bsm)
        bsms = [str(item.bsm) for item in rows]
        binding = zone.model_dump(mode="json")
        binding["authoritative_zone_assignments"] = [
            item.model_dump(mode="json") for item in rows
        ]
        balance = zone_balances.get(target_id)
        if balance is not None:
            binding["zone_area_balance"] = balance.model_dump(mode="json")
        decision.target_assignments.append(
            TargetAssignment(
                target_id=target_id,
                target_type="zone",
                status="placed" if allocation_ready and bsms else "unplaced",
                selected_bsm=bsms[0] if allocation_ready and bsms else "",
                selected_bsms=bsms if allocation_ready else [],
                expected_output_kind=zone.expected_output_kind,
                target_binding=binding,
                reason=(
                    ""
                    if allocation_ready and bsms
                    else f"global_zone_allocation_{str(getattr(zone_allocation, 'status', 'missing')).lower()}"
                ),
                score=(
                    sum(float(item.suitability_score) for item in rows) / len(rows)
                    if allocation_ready and rows
                    else 0.0
                ),
                allocation_lineage_refs=[item.lineage.lineage_id for item in rows]
                if allocation_ready
                else [],
            )
        )
        assigned_ids.add(target_id)
    decision.decision_factors["global_zone_allocation"] = {
        "status": str(getattr(zone_allocation, "status", "missing")),
        "complete": bool(getattr(zone_allocation, "complete", False)),
        "assignment_count": len(zone_rows),
        "diagnostic_codes": [
            str(getattr(item, "code", ""))
            for item in list(getattr(zone_allocation, "diagnostics", None) or [])
        ],
    }
    for target_type, targets in (
        ("site_area", all_projects),
        ("axis", list(getattr(intent, "development_axes", None) or [])),
        ("road", list(getattr(intent, "road_targets", None) or [])),
        ("linear", list(getattr(intent, "linear_targets", None) or [])),
    ):
        for target in targets:
            target_id = str(getattr(target, "target_id", "") or "")
            if not target_id or target_id in assigned_ids:
                continue
            status = "ready"
            reason = ""
            if target_type == "road":
                road_ready, reason = _road_contract_ready(target)
                status = "ready" if road_ready else "unplaced"
            elif target_type == "axis" and not (
                getattr(target, "start_anchor", None)
                and getattr(target, "end_anchor", None)
            ):
                status = "unplaced"
                reason = "axis_endpoints_unresolved"
            decision.target_assignments.append(
                TargetAssignment(
                    target_id=target_id,
                    target_type=target_type,
                    status=status,
                    expected_output_kind=getattr(target, "expected_output_kind", "parcel"),
                    target_binding=target.model_dump(mode="json"),
                    reason=reason,
                )
            )
    decision.refresh_derived_summaries()
    logger.info(
        "select_aggregate: zone/road assignments %.2fs (zones=%d)",
        time.monotonic() - _t_zones,
        len(list(getattr(intent, "zone_targets", None) or [])),
    )
    _t_briefs = time.monotonic()
    projects_by_target = {project.target_id: project for project in all_projects}
    briefs = [
        build_land_design_brief(projects_by_target[placement.target_id], placement, context)
        for placement in placements
        if placement.status == "placed" and placement.target_id in projects_by_target
    ]
    logger.info(
        "select_aggregate: decision/briefs %.2fs (assignments=%d placed=%d briefs=%d)",
        time.monotonic() - _t_briefs, len(decision.target_assignments),
        len([a for a in decision.target_assignments if a.status == "placed"]), len(briefs),
    )
    return decision, briefs


def revise_site_selection_deferral(
    decision: SiteSelectionDecision,
    target_ids: list[str],
    *,
    review_status: str = "deferred",
    run_id: str = "",
    session_id: str = "",
) -> SiteSelectionDecision:
    """Apply an explicit human deferral to a ``SiteSelectionDecision`` revision.

    ``review_status="deferred"`` marks the affected assignments deferred and
    accumulates ``deferred_targets`` into ``decision_factors`` (HUMAN target
    deferral path). Any other status mirrors the human-approved SELECT revision:
    the decision factors are replaced with the deferred snapshot and
    ``review_status`` is stamped ``human_approved``. Pure construction — the
    caller owns CAS writes.
    """
    deferred = [str(target_id) for target_id in target_ids]
    revised = decision.model_copy(deep=True)
    factors = dict(revised.decision_factors or {})
    if review_status == "deferred":
        deferred_set = set(deferred)
        revised.target_assignments = [
            assignment.model_copy(update={"status": "deferred"})
            if assignment.target_id in deferred_set
            else assignment
            for assignment in revised.target_assignments
        ]
        prior = [str(value) for value in factors.get("deferred_targets", [])]
        factors["deferred_targets"] = list(dict.fromkeys(prior + deferred))
        factors["deferred_by"] = "human_review"
        revised.decision_factors = factors
        revised.refresh_derived_summaries()
    else:
        factors.update({
            "unplaced_count": 0,
            "deferred_count": len(deferred),
            "deferred_targets": deferred,
            "deferred_by": "human_review",
        })
        revised.decision_factors = factors
        revised.review_status = "human_approved"
    return revised


__all__ = [
    "select_aggregate",
    "build_site_selection_decision",
    "build_land_design_brief",
    "revise_site_selection_deferral",
]
