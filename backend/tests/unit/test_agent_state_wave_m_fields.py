"""AgentState Wave M1 conservative additions tests."""

from app.agent.plan_state.state import AgentState, create_initial_state


def test_initial_state_has_m1_fields():
    state = create_initial_state(session_id="s1", project_name="金田村", village_data="")
    assert state["delivery_manifest"] is None
    assert state["reconciliation_report_ref"] is None
    assert state["validation_report_ref"] is None
    assert state["pending_requests"] == []
    assert state["context_version"] == ""


def test_initial_state_removes_legacy_gis_fields():
    state = create_initial_state(session_id="s1", project_name="金田村", village_data="")
    for key in (
        "gis_layout_configs",
        "gis_export_result",
        "gis_render_result",
        "gis_render_artifact",
        "gis_validation_result",
        "gis_execution_errors",
        "gis_conflict_result",
    ):
        assert key not in state, key


def test_m1_fields_are_in_typed_state():
    keys = set(AgentState.__annotations__.keys())
    for key in (
        "delivery_manifest",
        "reconciliation_report_ref",
        "validation_report_ref",
        "pending_requests",
        "context_version",
    ):
        assert key in keys, key
    # legacy gis_* fields removed (deprecated, use delivery_manifest)
    for key in (
        "gis_layout_configs",
        "gis_export_result",
        "gis_render_result",
        "gis_render_artifact",
        "gis_validation_result",
        "gis_execution_errors",
        "gis_conflict_result",
    ):
        assert key not in keys, key
