"""DELIVER aggregate tests — traceability/deliverables builders + orchestrator."""

from types import SimpleNamespace

from app.agent.deliver.aggregate import (
    build_deliverables_from_export,
    build_traceability_from_coverage,
    collect_upstream_human_items,
    deliver_aggregate,
)
from app.modules.schema.contracts.reconciliation_contracts import (
    CoverageMatrix,
    CoverageMatrixRow,
    ReconciliationReport,
)
from app.modules.schema.contracts.validation_report_contracts import (
    ValidationCheck,
    ValidationReport,
)
from app.modules.schema.contracts.workflow_contracts import (
    GateDecision,
    PendingRequest,
)

REQUIRED_LAYERS = (
    "admin_area",
    "current_landuse",
    "planned_landuse",
    "ecological_redline",
    "farmland_protection",
    "construction_zone",
)


def _full_export():
    lines = [f"output/layer_{l}.geojson" for l in REQUIRED_LAYERS]
    return {"exported_files": ["\n".join(lines)]}


def _covered_matrix():
    return CoverageMatrix(
        rows=[
            CoverageMatrixRow(
                intervention_id="iv-1",
                spec_index=0,
                candidate_site_id="cand-1",
                selected_bsm="BSM001",
                change_bsm="BSM001",
                planned_parcel_bsm="BSM001",
                status="covered",
            )
        ]
    )


def _passed_validation():
    vc = ValidationCheck(check_id="classification_missing", passed=True)
    return ValidationReport(checks=[vc], overall_passed=True)


def _planned_state():
    p = SimpleNamespace(
        bsm="BSM001",
        planning_land_use="0101",
        zone_type="农田保护区",
        area_ha=10.0,
    )
    return SimpleNamespace(parcels=[p], zones=[], facilities=[], roads=[], axes=[])


def _current_parcels():
    p = SimpleNamespace(dlbm="0101", area_sqm=100000.0)
    return [p]


def _pass_gate():
    return GateDecision(stage="validate", passed=True, feedback_route=None)


def test_build_traceability_from_coverage_full():
    entries = build_traceability_from_coverage(_covered_matrix())
    assert len(entries) == 1
    e = entries[0]
    assert e.intervention_id == "iv-1"
    assert e.requirement_id == "0"
    assert e.candidate_id == "cand-1"
    assert e.selection_id == "BSM001"
    assert e.change_id == "BSM001"
    assert e.planned_ref == "BSM001"
    assert e.deliverable_id == ""


def test_build_traceability_from_coverage_empty():
    assert build_traceability_from_coverage(CoverageMatrix(rows=[])) == []


def test_build_deliverables_from_export():
    dels = build_deliverables_from_export(_full_export())
    assert len(dels) == 1
    assert dels[0].deliverable_id == "deliverable-0"
    assert "admin_area" in dels[0].path


def test_build_deliverables_from_none():
    assert build_deliverables_from_export(None) == []


def test_collect_upstream_human_items():
    gates = [
        GateDecision(
            stage="validate",
            passed=False,
            feedback_route="HUMAN",
            pending_requests=[
                PendingRequest(
                    request_id="pr-validate-human-0",
                    stage="validate",
                    request_type="validate_human",
                    context={"reason": "HUMAN"},
                )
            ],
        ),
        _pass_gate(),
    ]
    items = collect_upstream_human_items(gates)
    assert len(items) == 1
    assert items[0].blocking is True
    assert items[0].item_id == "hi-upstream-0"


def test_deliver_aggregate_full_pass():
    manifest = deliver_aggregate(
        _planned_state(),
        _passed_validation(),
        ReconciliationReport(coverage_matrix=_covered_matrix(), inconsistencies=[]),
        [_pass_gate()],
        _full_export(),
        current_parcels=_current_parcels(),
        run_id="run-1",
    )
    assert manifest.statutory_complete is True
    assert manifest.statutory_complete_breakdown["delivery_gate"] is True
    assert len(manifest.traceability) == 1
    assert manifest.pending_human_items == []
    assert manifest.delivery_gate is not None
    assert manifest.delivery_gate.passed is True


def test_deliver_aggregate_blocks_on_classification_missing():
    vc = ValidationCheck(check_id="classification_missing", passed=False)
    vr = ValidationReport(checks=[vc], overall_passed=False)
    manifest = deliver_aggregate(
        _planned_state(),
        vr,
        ReconciliationReport(coverage_matrix=_covered_matrix(), inconsistencies=[]),
        [_pass_gate()],
        _full_export(),
        current_parcels=_current_parcels(),
        run_id="run-1",
    )
    assert manifest.statutory_complete is False
    assert manifest.statutory_complete_breakdown["classification_complete"] is False
    assert any(i.item_id == "hi-class-0" for i in manifest.pending_human_items)
    assert any(i.blocking for i in manifest.pending_human_items)


def test_deliver_aggregate_statutory_complete_breakdown():
    manifest = deliver_aggregate(
        _planned_state(),
        _passed_validation(),
        ReconciliationReport(coverage_matrix=_covered_matrix(), inconsistencies=[]),
        [_pass_gate()],
        None,  # export missing -> blocking layers item
        current_parcels=_current_parcels(),
        run_id="run-1",
    )
    assert manifest.statutory_complete is False
    assert manifest.statutory_complete_breakdown == {
        "delivery_gate": True,
        "no_blocking_items": False,
        "classification_complete": True,
    }
    assert any(i.item_id.startswith("hi-layers-") for i in manifest.pending_human_items)
