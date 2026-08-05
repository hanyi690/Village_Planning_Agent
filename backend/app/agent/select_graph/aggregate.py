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

from typing import Any, List, Optional, Tuple

from app.agent.select_graph.adapter import grounding_to_candidate_parcels
from app.modules.context.planning_context import PlanningContext
from app.modules.schema.contracts.grounding_contracts import GroundingResult
from app.modules.schema.contracts.parse_contracts import ProjectTarget
from app.modules.schema.contracts.provenance import Provenance
from app.modules.schema.contracts.selection_contracts import (
    EliminatedCandidate,
    LandDesignBrief,
    RankedCandidate,
    SiteSelectionDecision,
)
from app.modules.spatial_ops.selection import (
    PlacementDecision,
    ScoredCandidate,
    SelectionTarget,
    select_parcel,
)

_SCORE_BREAKDOWN_STUBS = {
    "proximity": 0.0,
    "construction": 0.0,
    "area_fit": 0.0,
    "road_access": 0.0,
    "service_coverage": 0.0,
}


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
        project_ref=project.project_id,
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
    selected_combination = [d.selected_bsm for d in placements if d.status == "placed"]
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
                )
            )
        else:
            best_score_by_target[placement.target_id] = 0.0
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
        selected_combination=selected_combination,
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
            module="app.agent.select_graph.aggregate",
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


def select_aggregate(
    result: GroundingResult,
    intent: Any,
    context: PlanningContext,
) -> Tuple[SiteSelectionDecision, List[LandDesignBrief]]:
    run_id = getattr(context, "session_id", "") or ""
    if context.bundle is None:
        empty = build_site_selection_decision([], run_id=run_id, session_id=run_id)
        return empty, []
    parcels = grounding_to_candidate_parcels(result, context.bundle)
    projects = list(getattr(intent, "project_targets", None) or [])
    cluster_centroid = _cluster_centroid(context)
    occupied: List[Tuple[float, float]] = []
    placements: List[PlacementDecision] = []
    for project in projects:
        target = SelectionTarget(
            target_id=project.project_id,
            name=project.name,
            category="project",
            scale_text=project.scale_text,
        )
        placement = select_parcel(
            target,
            candidates=parcels,
            constraint_index=context.constraint_index,
            hazards=None,
            occupied=occupied,
            cluster_centroid=cluster_centroid,
        )
        if placement.status == "placed" and placement.anchor_point is not None:
            occupied.append(placement.anchor_point)
        placements.append(placement)
    decision = build_site_selection_decision(placements, run_id=run_id, session_id=run_id)
    briefs = [
        build_land_design_brief(project, placement, context)
        for project, placement in zip(projects, placements)
        if placement.status == "placed"
    ]
    return decision, briefs


__all__ = [
    "select_aggregate",
    "build_site_selection_decision",
    "build_land_design_brief",
]
