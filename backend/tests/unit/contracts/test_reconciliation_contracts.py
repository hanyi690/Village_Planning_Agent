from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.modules.schema.contracts.reconciliation_contracts import (
    CoverageMatrix,
    CoverageMatrixRow,
    ReconciliationInconsistency,
    ReconciliationReport,
)


def test_coverage_matrix_row_all_fields():
    row = CoverageMatrixRow(
        intervention_id="int-1",
        spec_index=0,
        candidate_site_id="site_1_P001",
        selected_bsm="P001",
        change_bsm="P001",
        planned_parcel_bsm="P001",
        status="covered",
    )
    assert row.intervention_id == "int-1"
    assert row.spec_index == 0
    assert row.candidate_site_id == "site_1_P001"
    assert row.selected_bsm == "P001"
    assert row.change_bsm == "P001"
    assert row.planned_parcel_bsm == "P001"
    assert row.status == "covered"


def test_coverage_matrix_row_defaults():
    row = CoverageMatrixRow()
    assert row.intervention_id == ""
    assert row.spec_index is None
    assert row.status == "missing"


def test_coverage_matrix_row_status_literal():
    with pytest.raises(ValidationError):
        CoverageMatrixRow(status="invalid_status")


def test_coverage_matrix_accepts_rows():
    rows = [CoverageMatrixRow(intervention_id="int-1", status="covered")]
    matrix = CoverageMatrix(rows=rows)
    assert len(matrix.rows) == 1
    assert matrix.rows[0].intervention_id == "int-1"


def test_reconciliation_inconsistency_responsible_stage():
    inc = ReconciliationInconsistency(
        intervention_id="int-1",
        field="spec",
        expected="spec-1",
        actual="",
        severity="error",
        responsible_stage="L3",
    )
    assert inc.responsible_stage == "L3"
    assert inc.severity == "error"


def test_reconciliation_inconsistency_default_stage():
    inc = ReconciliationInconsistency(intervention_id="int-1")
    assert inc.responsible_stage == "EXECUTE"
    assert inc.severity == "warning"


def test_reconciliation_inconsistency_stage_literal():
    with pytest.raises(ValidationError):
        ReconciliationInconsistency(responsible_stage="INVALID")


def test_reconciliation_report_roundtrip():
    report = ReconciliationReport(
        coverage_matrix=CoverageMatrix(
            rows=[CoverageMatrixRow(intervention_id="int-1", status="covered")]
        ),
        inconsistencies=[
            ReconciliationInconsistency(
                intervention_id="int-2",
                field="planned",
                expected="PP-2",
                actual="",
                severity="error",
                responsible_stage="EXECUTE",
            )
        ],
    )
    assert len(report.coverage_matrix.rows) == 1
    assert report.coverage_matrix.rows[0].status == "covered"
    assert len(report.inconsistencies) == 1
    assert report.inconsistencies[0].responsible_stage == "EXECUTE"
