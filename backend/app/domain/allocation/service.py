"""Deterministic allocation projection from a typed SELECT decision."""

from __future__ import annotations

from app.domain.allocation.model import AllocationAssignment, PortfolioDecision
from app.domain.demand.model import DemandPortfolio
from app.domain.suitability.model import SuitabilitySurface


def build_portfolio_decision(
    demand: DemandPortfolio,
    suitability: SuitabilitySurface,
    selection: object,
) -> PortfolioDecision:
    """Convert explicit target assignments into the allocation root artifact.

    This function does not invent a candidate.  It only projects an existing
    target-bound selection and records every unmet demand explicitly.
    """

    candidates = {item.candidate_id: item for item in suitability.candidates}
    candidates_by_parcel = {
        parcel: candidate
        for candidate in suitability.candidates
        for parcel in candidate.source_parcels
    }
    assignments_by_target = {
        str(item.target_id): item
        for item in (getattr(selection, "target_assignments", ()) or ())
    }
    output: list[AllocationAssignment] = []
    unmet: list[str] = []
    score = 0.0
    for item in demand.demands:
        selected = assignments_by_target.get(item.target_id)
        if item.geometry_kind == "action":
            output.append(
                AllocationAssignment(
                    demand_id=item.demand_id,
                    target_id=item.target_id,
                    status="action",
                    reason="non_spatial_action",
                )
            )
            continue
        if selected is None or selected.status in {"ready", "unplaced"}:
            unmet.append(item.demand_id)
            output.append(
                AllocationAssignment(
                    demand_id=item.demand_id,
                    target_id=item.target_id,
                    status="unplaced",
                    reason=str(getattr(selected, "reason", "no_target_assignment") or "no_target_assignment"),
                )
            )
            continue
        if selected.status == "deferred":
            output.append(
                AllocationAssignment(
                    demand_id=item.demand_id,
                    target_id=item.target_id,
                    candidate_id=str(selected.selected_bsm or ""),
                    status="deferred",
                    reason=str(selected.reason or "human_deferred"),
                )
            )
            continue
        candidate = candidates.get(str(selected.selected_bsm)) or candidates_by_parcel.get(
            str(selected.selected_bsm)
        )
        if candidate is None:
            unmet.append(item.demand_id)
            output.append(
                AllocationAssignment(
                    demand_id=item.demand_id,
                    target_id=item.target_id,
                    candidate_id=str(selected.selected_bsm or ""),
                    status="unplaced",
                    reason="selected_candidate_not_in_suitability_surface",
                )
            )
            continue
        if not candidate.hard_feasible:
            unmet.append(item.demand_id)
            output.append(
                AllocationAssignment(
                    demand_id=item.demand_id,
                    target_id=item.target_id,
                    candidate_id=candidate.candidate_id,
                    status="unplaced",
                    reason="selected_candidate_not_hard_feasible",
                )
            )
            continue
        score += candidate.score
        output.append(
            AllocationAssignment(
                demand_id=item.demand_id,
                target_id=item.target_id,
                candidate_id=candidate.candidate_id,
                source_parcels=list(candidate.source_parcels),
                status="assigned",
            )
        )
    has_deferred = any(item.status == "deferred" for item in output)
    solver_status = "INFEASIBLE" if unmet else ("FEASIBLE" if has_deferred else "OPTIMAL")
    return PortfolioDecision(
        solver_status=solver_status,
        assignments=output,
        unmet_demand=unmet,
        objective_value=score,
        diagnostics=( ["unmet_demand_present"] if unmet else []),
    )


__all__ = ["build_portfolio_decision"]
