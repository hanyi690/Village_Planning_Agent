"""RECONCILE gate tests - evaluate_reconcile_gate / reconcile_gate_route (Wave K Task 4)."""

from app.agent.reconcile.gate import evaluate_reconcile_gate, reconcile_gate_route
from app.modules.schema.contracts.reconciliation_contracts import (
    ReconciliationInconsistency,
    ReconciliationReport,
)


def _inc(stage, severity="error"):
    return ReconciliationInconsistency(
        intervention_id="i",
        field="x",
        expected="a",
        actual="b",
        severity=severity,
        responsible_stage=stage,
    )


def _report(inconsistencies):
    return ReconciliationReport(inconsistencies=inconsistencies)


def _passing_report():
    return ReconciliationReport(inconsistencies=[])


def test_pass():
    report = _passing_report()
    d = evaluate_reconcile_gate(report)

    assert reconcile_gate_route(report) == "PASS"
    assert d.passed is True
    assert d.feedback_route is None
    assert d.stage == "reconcile"
    assert d.pending_requests == []


def test_pass_warnings_only():
    report = _report([_inc("L3", severity="warning")])
    d = evaluate_reconcile_gate(report)

    assert reconcile_gate_route(report) == "PASS"
    assert d.passed is True
    assert d.feedback_route is None


def test_retry_l3():
    report = _report([_inc("L3"), _inc("L3"), _inc("EXECUTE")])
    d = evaluate_reconcile_gate(report)

    assert reconcile_gate_route(report) == "RETRY_L3"
    assert d.passed is False
    assert d.feedback_route == "RETRY_L3"


def test_retry_execute():
    report = _report([_inc("EXECUTE"), _inc("EXECUTE"), _inc("L3")])
    d = evaluate_reconcile_gate(report)

    assert reconcile_gate_route(report) == "RETRY_EXECUTE"
    assert d.passed is False
    assert d.feedback_route == "RETRY_EXECUTE"


def test_human_tie():
    report = _report([_inc("L3"), _inc("EXECUTE")])
    d = evaluate_reconcile_gate(report)

    assert reconcile_gate_route(report) == "HUMAN"
    assert d.passed is False
    assert d.feedback_route == "HUMAN"


def test_human_ground_stage():
    report = _report([_inc("GROUND"), _inc("GROUND")])
    d = evaluate_reconcile_gate(report)

    assert reconcile_gate_route(report) == "HUMAN"
    assert d.passed is False
    assert d.feedback_route == "HUMAN"


def test_pending_requests():
    report = _report([_inc("L3"), _inc("L3"), _inc("EXECUTE")])
    d = evaluate_reconcile_gate(report)

    assert len(d.pending_requests) == 1
    pr = d.pending_requests[0]
    assert "l3" in pr.request_type
    assert pr.context["reason"] == "RETRY_L3"
    assert pr.context["stage"] == "L3"
    assert pr.context["error_count"] == 2
    assert pr.stage == "reconcile"


def test_deterministic():
    report = _report([_inc("EXECUTE"), _inc("EXECUTE"), _inc("L3")])

    d1 = evaluate_reconcile_gate(report)
    d2 = evaluate_reconcile_gate(report)

    assert reconcile_gate_route(report) == reconcile_gate_route(report)
    assert d1.passed == d2.passed
    assert d1.model_dump(exclude={"created_at"}) == d2.model_dump(exclude={"created_at"})
