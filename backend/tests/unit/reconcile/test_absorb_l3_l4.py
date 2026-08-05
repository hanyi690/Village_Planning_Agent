from __future__ import annotations

import asyncio
from pathlib import Path

from app.agent.execute.execute_state import ExecuteAgentState
from app.modules.schema.contracts.parse_contracts import SpatialPlanningIntent


def test_execute_agent_no_l3_l4_consistency_helper():
    """The L3/L4 consistency logic was absorbed into reconcile_aggregate; the
    dict-returning helper must be gone from execute_agent.py."""
    source = Path(
        "app/agent/execute/execute_agent.py"
    ).read_text(encoding="utf-8-sig")
    assert "_build_l3_l4_consistency_report" not in source


def test_validate_node_does_not_call_l3_l4_helper():
    source = Path(
        "app/agent/execute/execute_agent.py"
    ).read_text(encoding="utf-8-sig")
    assert "_build_l3_l4_consistency_report(state)" not in source


def test_reconcile_aggregate_covers_l3_l4_targets():
    """reconcile_aggregate detects a missing project/road vs planned output."""
    from app.agent.reconcile.aggregate import reconcile_aggregate
    from app.modules.schema.contracts.l3_contracts import PlanningProgram
    from app.modules.schema.contracts.parse_contracts import ProjectTarget, RoadTarget
    from app.modules.schema.contracts.planned_state_contracts import PlannedState

    intent = SpatialPlanningIntent(
        project_targets=[ProjectTarget(project_id="p1", name="P1")],
        road_targets=[RoadTarget(road_level="village_road")],
        zone_targets=[],
    )
    report = reconcile_aggregate(
        PlanningProgram(interventions=[]),
        [],
        None,
        None,
        None,
        PlannedState(parcels=[], roads=[]),
        intent,
        run_id="s1",
    )
    fields = {inc.field for inc in report.inconsistencies}
    assert "l3_l4_project" in fields
    assert "l3_l4_road" in fields


def test_state_reconciliation_report_field_default():
    state = ExecuteAgentState()
    assert state.reconciliation_report is None


def test_state_reconciliation_report_field_settable():
    state = ExecuteAgentState(reconciliation_report={"dummy": True})
    assert state.reconciliation_report == {"dummy": True}


def test_execution_review_still_works():
    """_execution_review_node runs without the removed helper (empty -> fail path)."""
    from app.agent.execute.execute_agent import _execution_review_node

    state = ExecuteAgentState(
        session_id="s1",
        layout_configs=[],
        validation_result={},
    )
    result = asyncio.run(_execution_review_node(state))
    assert result["validation_result"]["passed"] is False
    assert result["validation_result"]["reason"] == "execution_review_failed"
