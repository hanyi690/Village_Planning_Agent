"""Regression tests for real spatial execution boundaries."""

from __future__ import annotations

from app.contracts.spatial.global_site_allocation_contracts import (
    GlobalSiteAllocationProblem,
    SiteCandidateEvidence,
    SiteParcelCapacity,
    SiteTargetDemand,
)
from app.domain.materialization.execute_agent import _route_after_execution_review
from app.domain.materialization.execute_state import ExecuteAgentState
from app.spatial.allocation.global_site_allocator import allocate_global_sites


def _candidate(target_id: str, bsm: str) -> SiteCandidateEvidence:
    return SiteCandidateEvidence(
        target_id=target_id,
        bsm=bsm,
        candidate_id=f"candidate:{target_id}:{bsm}",
        anchor_point=(116.0, 24.0),
        suitability_score=0.9,
        score_breakdown={
            "slope_hazard": 0.9,
            "hazard_safety": 0.9,
            "road_access": 0.9,
            "service_coverage": 0.9,
        },
        hard_feasible=True,
        evidence_refs=[f"evidence:{target_id}:{bsm}"],
    )


def test_point_target_does_not_consume_parcel_area_capacity():
    problem = GlobalSiteAllocationProblem(
        targets=[
            SiteTargetDemand(
                target_id="facility:bus-stop:001",
                target_type="facility",
                expected_output_kind="point",
                required_area_m2=0.0,
                target_binding={"service_radius_m": 300},
                provenance_refs=["report:需求台账:公交车站点"],
            )
        ],
        candidates=[_candidate("facility:bus-stop:001", "B001")],
        parcels=[
            SiteParcelCapacity(
                bsm="B001",
                capacity_area_m2=100.0,
                geometry_ref="bundle:landuse_current:B001",
                provenance_refs=["bundle:landuse_current:B001"],
            )
        ],
    )

    result = allocate_global_sites(problem)

    assert result.complete is True
    assert result.assignments[0].status == "assigned"
    assert result.assignments[0].consumed_area_m2 == 0.0
    assert result.assignments[0].anchor_point == (116.0, 24.0)


def test_route_error_retries_route_boundary_after_l3_kg_rehydrate():
    state = ExecuteAgentState(
        validation_result={"passed": False},
        validation_round=1,
        execution_errors=[
            {
                "stage": "route",
                "code": "kg_l3_intent_mismatch",
            }
        ],
    )

    assert _route_after_execution_review(state) == "retry_route"


def test_non_route_execution_error_keeps_worker_retry_path():
    state = ExecuteAgentState(
        validation_result={"passed": False},
        validation_round=1,
        execution_errors=[
            {
                "stage": "worker",
                "code": "worker_output_invalid",
            }
        ],
    )

    assert _route_after_execution_review(state) == "retry"
