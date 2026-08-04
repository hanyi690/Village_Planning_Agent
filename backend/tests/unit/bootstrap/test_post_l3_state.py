"""PostL3ChainState contract tests."""

from app.agent.bootstrap.post_l3_state import PostL3ChainState
from app.modules.schema.contracts.delivery_manifest_contracts import DeliveryManifest
from app.modules.schema.contracts.reconciliation_contracts import ReconciliationReport
from app.modules.schema.contracts.validation_report_contracts import ValidationReport


def test_post_l3_state_defaults():
    state = PostL3ChainState()
    assert state.session_id == ""
    assert state.specs == []
    assert state.layout_configs == []
    assert state.upstream_gates == []
    assert state.export_result is None
    assert state.context is None
    assert state.planning_program is None
    assert state.delivery_manifest is None


def test_post_l3_state_round_trip_typed():
    dm = DeliveryManifest(statutory_complete=True)
    vr = ValidationReport(overall_passed=True)
    rr = ReconciliationReport()
    state = PostL3ChainState(
        session_id="s1",
        village_name="金田村",
        validation_report=vr,
        reconciliation_report=rr,
        delivery_manifest=dm,
        upstream_gates=[dm],
        export_result={"status": "completed", "exported_files": ["a.geojson"]},
    )
    assert state.session_id == "s1"
    assert state.delivery_manifest.statutory_complete is True
    assert state.validation_report.overall_passed is True
    assert state.reconciliation_report is rr
    assert len(state.upstream_gates) == 1
    assert state.export_result["status"] == "completed"


def test_post_l3_state_accumulates_lists():
    state = PostL3ChainState(
        specs=["spec-1", "spec-2"],
        land_design_briefs=["brief-1"],
        upstream_gates=[1, 2, 3],
    )
    assert len(state.specs) == 2
    assert len(state.upstream_gates) == 3
