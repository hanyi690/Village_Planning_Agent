"""SELECT must preserve target output semantics for EXECUTE dispatch."""

from app.domain.allocation.select_service import build_site_selection_decision
from app.modules.spatial_ops.selection import PlacementDecision


def test_selected_project_keeps_point_output_kind():
    decision = build_site_selection_decision(
        [
            PlacementDecision(
                target_id="project-1",
                selected_bsm="bsm-1",
                status="placed",
            )
        ],
        run_id="run-1",
        session_id="session-1",
        expected_output_kinds={"project-1": "point"},
    )

    assert decision.target_assignments[0].expected_output_kind == "point"
