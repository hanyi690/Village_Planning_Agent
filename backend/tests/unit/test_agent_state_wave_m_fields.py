"""AgentState Wave M1 conservative additions tests."""

from app.agent.plan_state.state import AgentState, create_initial_state


def test_initial_state_has_m1_fields():
    state = create_initial_state(session_id="s1", project_name="金田村", village_data="")
    assert state["pending_requests"] == []
    assert state["context_version"] == ""
    assert state["context_fingerprint"] == ""
    assert state["bootstrap_context_done"] is False
    assert state["artifact_refs"] == {}


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
        "pending_requests",
        "context_version",
        "context_fingerprint",
        "bootstrap_context_done",
        "artifact_refs",
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
    for key in (
        "delivery_manifest",
        "planning_program",
        "grounding_result",
        "site_selection",
        "execution_plan",
        "parcel_changeset",
        "planned_state",
        "validation_report",
        "reconciliation_report",
        "allocated_geojson",
        "render_result",
        "grounding_result_ref",
        "site_selection_ref",
        "parcel_changeset_ref",
        "planned_state_ref",
        "validation_report_ref",
        "reconciliation_report_ref",
        "l3_program_ref",
    ):
        assert key not in keys, key
