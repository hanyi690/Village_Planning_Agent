from app.domain.allocation.select_gate import evaluate_select_gate
from app.domain.allocation import build_portfolio_decision
from app.domain.demand import derive_demand_portfolio
from app.domain.suitability import build_suitability_surface
from app.contracts.spatial.grounding_contracts import (
    CandidateSite,
    GroundingResult,
    HardConstraintResult,
)
from app.contracts.workflow.parse_contracts import (
    LinearAssetTarget,
    SiteAreaTarget,
    SpatialPlanningIntent,
)
from app.contracts.domain.selection_contracts import SiteSelectionDecision, TargetAssignment


def _intent() -> SpatialPlanningIntent:
    return SpatialPlanningIntent(
        village_name="test-village",
        site_area_targets=[
            SiteAreaTarget(
                site_area_id="site-area-1",
                target_id="site-area-1",
                name="公共服务点",
                area_ha=1.5,
            )
        ],
    )


def _grounding(*, hard_passed: bool = True) -> GroundingResult:
    return GroundingResult(
        candidates=[
            CandidateSite(
                site_id="candidate-1",
                target_ref="site-area-1",
                source_parcels=["parcel-1"],
                metrics={"confidence": 0.9},
                hard_constraint_result=HardConstraintResult(passed=hard_passed),
            )
        ]
    )


def test_demand_is_typed_and_does_not_contain_parcel_candidates():
    portfolio = derive_demand_portfolio(_intent())

    assert [item.target_id for item in portfolio.demands] == ["site-area-1"]
    assert portfolio.demands[0].quantity == 1.5
    assert "source_parcels" not in portfolio.demands[0].model_dump()


def test_linear_asset_demand_preserves_canonical_linear_kind():
    intent = SpatialPlanningIntent(
        village_name="test-village",
        linear_targets=[
            LinearAssetTarget(
                target_id="linear-1",
                name="雨污分流管网",
                asset_kind="stormwater",
            )
        ],
    )

    portfolio = derive_demand_portfolio(intent)

    assert portfolio.demands[0].kind == "linear"
    assert portfolio.demands[0].geometry_kind == "line"


def test_suitability_exposes_grounding_evidence_without_allocating():
    surface = build_suitability_surface(_grounding())

    assert len(surface.candidates) == 1
    assert surface.candidates[0].source_parcels == ["parcel-1"]
    assert surface.candidates[0].hard_feasible is True


def test_allocation_accepts_only_explicit_placed_selection():
    demand = derive_demand_portfolio(_intent())
    surface = build_suitability_surface(_grounding())
    selection = SiteSelectionDecision(
        target_assignments=[
            TargetAssignment(
                target_id="site-area-1",
                target_type="site_area",
                status="placed",
                selected_bsm="parcel-1",
            )
        ]
    )

    decision = build_portfolio_decision(demand, surface, selection)

    assert decision.solver_status == "OPTIMAL"
    assert decision.assignments[0].status == "assigned"
    assert decision.assignments[0].candidate_id == "candidate-1"


def test_allocation_and_select_gate_fail_closed_when_hard_feasibility_is_unproven():
    demand = derive_demand_portfolio(_intent())
    surface = build_suitability_surface(_grounding(hard_passed=False))
    selection = SiteSelectionDecision(
        target_assignments=[
            TargetAssignment(
                target_id="site-area-1",
                target_type="site_area",
                status="placed",
                selected_bsm="parcel-1",
            )
        ]
    )

    decision = build_portfolio_decision(demand, surface, selection)
    gate = evaluate_select_gate(
        selection,
        target_count=1,
        portfolio_decision=decision,
    )

    assert decision.solver_status == "INFEASIBLE"
    assert decision.unmet_demand == ["demand:site-area-1"]
    assert gate.passed is False
    assert gate.route_reason == "portfolio_infeasible"
    assert gate.pending_requests[0].context["target_ids"] == ["site-area-1"]
