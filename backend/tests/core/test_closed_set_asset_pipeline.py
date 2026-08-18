from __future__ import annotations

import pytest

from app.contracts.domain.l3_contracts import PlanningIntervention, PlanningProgram
from app.contracts.domain.planning_semantics import LinearAssetPlanningParameters
from app.contracts.domain.selection_contracts import SiteSelectionDecision, TargetAssignment
from app.contracts.program import PlanningClaim
from app.contracts.workflow.execution_plan_contracts import WorkerType
from app.domain.materialization.plan_builder import build_execution_plan
from app.domain.program.target_projection.compile import _build_intent


def test_linear_asset_is_closed_set_and_does_not_use_road_parameters():
    claim = PlanningClaim(
        claim_id="sewer-1",
        statement="污水管网改造",
        suggested_category="road",
        suggested_output_kind="line",
        asset_kind="sewer",
        linear_parameters=LinearAssetPlanningParameters(
            action="upgrade",
            length_m=120,
            diameter_mm=300,
        ),
    )
    assert claim.asset_kind == "sewer"
    assert claim.linear_parameters is not None
    assert claim.road_parameters is None

    with pytest.raises(ValueError):
        PlanningClaim(
            claim_id="bad",
            statement="污水管网改造",
            suggested_category="road",
            suggested_output_kind="line",
            asset_kind="sewer",
            linear_parameters=LinearAssetPlanningParameters(length_m=120),
            road_parameters={"road_level": "支路", "length_m": 120},
        )


def test_asset_kind_survives_projection_and_unsupported_worker_is_deferred():
    intervention = PlanningIntervention(
        intervention_id="sewer-1",
        name="污水管网改造",
        execution_mode="spatial",
        expected_output_kind="line",
        category="road",
        asset_kind="sewer",
        linear_parameters=LinearAssetPlanningParameters(
            action="upgrade",
            length_m=120,
            diameter_mm=300,
        ),
    )
    intent = _build_intent(PlanningProgram(interventions=[intervention]))
    target = intent.linear_targets[0]
    assert target.asset_kind == "sewer"
    assert target.linear_diameter_mm == 300

    selection = SiteSelectionDecision(
        target_assignments=[
            TargetAssignment(
                target_id="sewer-1",
                target_type="linear",
                status="ready",
                expected_output_kind="line",
                target_binding=target.model_dump(mode="json"),
            )
        ]
    )
    plan = build_execution_plan(intent, selection, [])
    assert not plan.worker_tasks
    assert len(plan.deferred_tasks) == 1
    deferred = plan.deferred_tasks[0]
    assert deferred.worker_type == WorkerType.UTILITY_NETWORK
    assert deferred.required_capability == "linear.sewer"
    assert deferred.defer_reason == "unsupported_capability"
