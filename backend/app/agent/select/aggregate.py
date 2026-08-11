"""SELECT subgraph aggregate - deterministic orchestrator over select_parcel.

Consumes ``GroundingResult`` + ``SpatialPlanningIntent`` + ``PlanningContext``
and produces a ``tuple[SiteSelectionDecision, list[LandDesignBrief]]``.

Pure orchestration: selection is delegated to ``spatial_ops.selection.select_parcel``
per project target with priority-sequential conflict allocation (occupied anchor
points accumulate so a parcel taken by an earlier, higher-priority target is
rejected for later targets). No LLM, no kg imports; given the same inputs the
output is fully deterministic.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from app.modules.context.planning_context import PlanningContext
from app.modules.schema import DLBM_TO_DLMC
from app.modules.schema.contracts.grounding_contracts import CandidateSite, GroundingResult
from app.modules.schema.contracts.parse_contracts import ProjectTarget
from app.modules.schema.contracts.provenance import Provenance
from app.modules.schema.contracts.selection_contracts import (
    EliminatedCandidate,
    LandDesignBrief,
    RankedCandidate,
    SiteSelectionDecision,
    TargetAssignment,
)
from app.modules.spatial_ops.selection.facility_location import (
    DemandPoint,
    FacilityCandidate,
    solve_maximal_covering,
)
from app.modules.spatial_ops.selection import (
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
        dlbm = str(getattr(parcel, "dlbm", ""))
        parcels.append(
            CandidateParcel(
                bsm=str(bsm),
                geometry=getattr(parcel, "geometry", {}),
                dlbm=dlbm,
                dlmc=DLBM_TO_DLMC.get(dlbm, ""),
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
    project: ProjectTarget,
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
) -> SiteSelectionDecision:
    """Aggregate placement decisions into a ``SiteSelectionDecision``.

    Ranked scores come from ``select_parcel``'s per-candidate ranking: the
    winner's real score and 3-dimension breakdown are surfaced; the zero-stub
    ``road_access``/``service_coverage`` dimensions stay 0.0 until external
    network/facility data is wired in.
    """
    assignments: List[TargetAssignment] = []
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
                    target_type="project",
                    status="placed",
                    selected_bsm=placement.selected_bsm,
                    anchor_point=placement.anchor_point,
                    expected_output_kind="parcel",
                    score=score,
                    score_breakdown=breakdown,
                )
            )
        else:
            best_score_by_target[placement.target_id] = 0.0
            assignments.append(
                TargetAssignment(
                    target_id=placement.target_id,
                    target_type="project",
                    status="unplaced",
                    expected_output_kind="parcel",
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
            module="app.agent.select.aggregate",
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
    bundle = getattr(context, "bundle", None)
    settlements = []
    if bundle is not None and getattr(bundle, "polygons", None) is not None:
        settlements = bundle.polygons.get("settlement") or []
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
    )
    if decision.status == "placed" and decision.anchor_point is not None:
        facility.anchor_point = decision.anchor_point
    return decision, decision.selected_bsm


def select_aggregate(
    result: GroundingResult,
    intent: Any,
    context: PlanningContext,
) -> Tuple[SiteSelectionDecision, List[LandDesignBrief]]:
    run_id = getattr(context, "session_id", "") or ""
    if context.bundle is None:
        empty = build_site_selection_decision([], run_id=run_id, session_id=run_id)
        return empty, []
    parcels = _grounding_to_candidate_parcels(result, context.bundle)
    projects = list(getattr(intent, "project_targets", None) or [])
    facilities = list(getattr(intent, "facilities", None) or [])
    cluster_centroid = _cluster_centroid(context)
    occupied: List[Tuple[float, float]] = []
    placements: List[PlacementDecision] = []
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
        target = SelectionTarget(
            target_id=project.target_id,
            name=project.name,
            category="project",
            scale_text=project.scale_text,
        )
        project_pool = _filter_parcels_for_target(parcels, project.target_id)
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
        )
        if placement.status == "placed" and placement.anchor_point is not None:
            occupied.append(placement.anchor_point)
        placements.append(placement)
    decision = build_site_selection_decision(placements, run_id=run_id, session_id=run_id)
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
    facility_placements: Dict[str, Dict[str, Any]] = {}
    facility_rank = len(placements) + 1
    for i, facility in enumerate(facilities):
        decision_p, bsm = _place_facility(
            facility, parcels, context, cluster_centroid, occupied
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
    assigned_ids = {assignment.target_id for assignment in decision.target_assignments}
    for target_type, targets in (
        ("project", projects),
        ("zone", list(getattr(intent, "zone_targets", None) or [])),
        ("axis", list(getattr(intent, "development_axes", None) or [])),
        ("road", list(getattr(intent, "road_targets", None) or [])),
    ):
        for target in targets:
            target_id = str(getattr(target, "target_id", "") or "")
            if not target_id or target_id in assigned_ids:
                continue
            decision.target_assignments.append(
                TargetAssignment(
                    target_id=target_id,
                    target_type=target_type,
                    status="ready",
                    expected_output_kind=getattr(target, "expected_output_kind", "parcel"),
                    target_binding=target.model_dump(mode="json"),
                )
            )
    decision.refresh_derived_summaries()
    projects_by_target = {project.target_id: project for project in projects}
    briefs = [
        build_land_design_brief(projects_by_target[placement.target_id], placement, context)
        for placement in placements
        if placement.status == "placed" and placement.target_id in projects_by_target
    ]
    return decision, briefs


__all__ = [
    "select_aggregate",
    "build_site_selection_decision",
    "build_land_design_brief",
]
