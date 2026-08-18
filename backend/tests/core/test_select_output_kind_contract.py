"""SELECT must preserve target output semantics for EXECUTE dispatch."""

from app.domain.allocation.select_service import build_site_selection_decision
from app.spatial.allocation.selection import PlacementDecision


def test_selected_facility_keeps_point_output_kind():
    decision = build_site_selection_decision(
        [
            PlacementDecision(
                target_id="facility-1",
                selected_bsm="bsm-1",
                status="placed",
            )
        ],
        run_id="run-1",
        session_id="session-1",
        expected_output_kinds={"facility-1": "point"},
    )

    assert decision.target_assignments[0].expected_output_kind == "point"
