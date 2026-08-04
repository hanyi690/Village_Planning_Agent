"""RECONCILE review package tests - build_reconcile_review_package (Wave K Task 5)."""

from __future__ import annotations

import json

from app.agent.reconcile.gate import evaluate_reconcile_gate
from app.agent.reconcile.review import build_reconcile_review_package
from app.modules.schema.contracts.provenance import Provenance
from app.modules.schema.contracts.reconciliation_contracts import (
    CoverageMatrix,
    CoverageMatrixRow,
    ReconciliationInconsistency,
    ReconciliationReport,
)

_SECTIONS = {
    "覆盖矩阵摘要",
    "链覆盖详情",
    "不一致清单",
    "面积偏差详情",
    "按阶段归因",
    "向后谱系",
    "Gate 决定",
    "来源追溯",
}


def _row(
    intervention_id="int-1",
    spec_index=0,
    candidate_site_id="site-0",
    selected_bsm="P001",
    change_bsm="P001",
    planned_parcel_bsm="P001",
    status="covered",
):
    return CoverageMatrixRow(
        intervention_id=intervention_id,
        spec_index=spec_index,
        candidate_site_id=candidate_site_id,
        selected_bsm=selected_bsm,
        change_bsm=change_bsm,
        planned_parcel_bsm=planned_parcel_bsm,
        status=status,
    )


def _missing_row(intervention_id="int-2"):
    return _row(
        intervention_id=intervention_id,
        spec_index=None,
        candidate_site_id="",
        selected_bsm="",
        change_bsm="",
        planned_parcel_bsm="",
        status="missing",
    )


def _inc(field="x", expected="a", actual="b", severity="error", stage="L3"):
    return ReconciliationInconsistency(
        intervention_id="int-1",
        field=field,
        expected=expected,
        actual=actual,
        severity=severity,
        responsible_stage=stage,
    )


def _report(rows=None, inconsistencies=None, provenance=None):
    return ReconciliationReport(
        coverage_matrix=CoverageMatrix(rows=list(rows or [])),
        inconsistencies=list(inconsistencies or []),
        provenance=provenance,
    )


def test_sections_present():
    report = _report(rows=[_row()], inconsistencies=[_inc()])
    gate = evaluate_reconcile_gate(report)
    package = build_reconcile_review_package(report, gate)
    assert set(package.keys()) == _SECTIONS


def test_coverage_summary():
    report = _report(rows=[_row(), _missing_row()])
    gate = evaluate_reconcile_gate(report)
    summary = build_reconcile_review_package(report, gate)["覆盖矩阵摘要"]
    assert summary["row_count"] == 2
    assert summary["by_status"] == {"covered": 1, "partial": 0, "missing": 1}
    assert len(summary["rows"]) == 2


def test_chain_coverage_details():
    report = _report(rows=[_row()])
    gate = evaluate_reconcile_gate(report)
    links = build_reconcile_review_package(report, gate)["链覆盖详情"]
    assert set(links.keys()) == {
        "intervention_to_spec",
        "spec_to_candidate",
        "candidate_to_selection",
        "selection_to_change",
        "change_to_planned",
    }


def test_inconsistency_list():
    report = _report(inconsistencies=[_inc(), _inc(field="area")])
    gate = evaluate_reconcile_gate(report)
    lst = build_reconcile_review_package(report, gate)["不一致清单"]
    assert len(lst) == 2
    assert lst[0]["field"] == "x"


def test_area_drift_section():
    report = _report(inconsistencies=[_inc(field="area", expected="10", actual="9.5"), _inc()])
    gate = evaluate_reconcile_gate(report)
    section = build_reconcile_review_package(report, gate)["面积偏差详情"]
    assert len(section) == 1
    assert section[0]["expected"] == "10"
    assert section[0]["actual"] == "9.5"


def test_stage_attribution():
    report = _report(
        inconsistencies=[
            _inc(stage="L3"),
            _inc(stage="L3"),
            _inc(stage="EXECUTE"),
            _inc(field="area", stage="GROUND"),
        ]
    )
    gate = evaluate_reconcile_gate(report)
    section = build_reconcile_review_package(report, gate)["按阶段归因"]
    assert section["L3"] == 2
    assert section["EXECUTE"] == 1
    assert section["GROUND"] == 1


def test_backward_lineage():
    report = _report(rows=[_row()])
    gate = evaluate_reconcile_gate(report)
    section = build_reconcile_review_package(report, gate)["向后谱系"]
    assert len(section) == 1
    assert section[0]["trace"][0] == "spec:0"


def test_gate_decision_section():
    report = _report(inconsistencies=[_inc(stage="L3"), _inc(stage="L3"), _inc(stage="EXECUTE")])
    gate = evaluate_reconcile_gate(report)
    section = build_reconcile_review_package(report, gate)["Gate 决定"]
    assert section["route"] == "RETRY_L3"
    assert section["passed"] is False
    assert section["rationale"]

    pass_report = _report()
    pass_gate = evaluate_reconcile_gate(pass_report)
    pass_section = build_reconcile_review_package(pass_report, pass_gate)["Gate 决定"]
    assert pass_section["route"] == "PASS"


def test_json_serializable():
    report = _report(
        rows=[_row(), _missing_row()],
        inconsistencies=[_inc(), _inc(field="area")],
    )
    gate = evaluate_reconcile_gate(report)
    package = build_reconcile_review_package(report, gate)
    json.dumps(package)


def test_provenance():
    provenance = Provenance(
        source="reconcile_aggregate",
        run_id="run-1",
        module="app.agent.reconcile.aggregate",
    )
    report = _report(rows=[_row()], provenance=provenance)
    gate = evaluate_reconcile_gate(report)
    section = build_reconcile_review_package(report, gate)["来源追溯"]
    assert section["source"] == "reconcile_aggregate"
