"""VALIDATE gate tests - evaluate_validate_gate / validate_gate_route."""

from app.agent.validate.gate import evaluate_validate_gate, validate_gate_route
from app.modules.schema.contracts.validation_report_contracts import (
    ValidationIssue,
    ValidationReport,
)


def _issue(stage, severity="error", code="c1", message="x"):
    return ValidationIssue(stage=stage, severity=severity, code=code, message=message)


def _report(overall_passed, issues_by_stage):
    return ValidationReport(
        overall_passed=overall_passed,
        issues_by_stage=issues_by_stage,
    )


def _errors(stage, n):
    return [_issue(stage) for _ in range(n)]


def test_pass():
    report = _report(overall_passed=True, issues_by_stage={})
    d = evaluate_validate_gate(report)

    assert validate_gate_route(report) == "PASS"
    assert d.passed is True
    assert d.feedback_route is None
    assert d.stage == "validate"
    assert d.pending_requests == []


def test_retry_execute():
    report = _report(False, {"EXECUTE": _errors("EXECUTE", 2), "SELECT": _errors("SELECT", 1)})
    d = evaluate_validate_gate(report)

    assert validate_gate_route(report) == "RETRY_EXECUTE"
    assert d.passed is False
    assert d.feedback_route == "RETRY_EXECUTE"


def test_retry_select():
    report = _report(False, {"SELECT": _errors("SELECT", 2), "EXECUTE": _errors("EXECUTE", 1)})
    d = evaluate_validate_gate(report)

    assert validate_gate_route(report) == "RETRY_SELECT"
    assert d.passed is False
    assert d.feedback_route == "RETRY_SELECT"


def test_retry_ground():
    report = _report(False, {"GROUND": _errors("GROUND", 2)})
    d = evaluate_validate_gate(report)

    assert validate_gate_route(report) == "RETRY_GROUND"
    assert d.passed is False
    assert d.feedback_route == "RETRY_GROUND"


def test_retry_l3():
    report = _report(False, {"L3": _errors("L3", 2)})
    d = evaluate_validate_gate(report)

    assert validate_gate_route(report) == "RETRY_L3"
    assert d.passed is False
    assert d.feedback_route == "RETRY_L3"


def test_human_tie():
    report = _report(False, {"EXECUTE": _errors("EXECUTE", 1), "SELECT": _errors("SELECT", 1)})
    d = evaluate_validate_gate(report)

    assert validate_gate_route(report) == "HUMAN"
    assert d.passed is False
    assert d.feedback_route == "HUMAN"


def test_human_warnings_only():
    report = _report(False, {"EXECUTE": [_issue("EXECUTE", severity="warning")]})
    d = evaluate_validate_gate(report)

    assert validate_gate_route(report) == "HUMAN"
    assert d.passed is False
    assert d.feedback_route == "HUMAN"


def test_pending_requests():
    report = _report(False, {"SELECT": _errors("SELECT", 2), "EXECUTE": _errors("EXECUTE", 1)})
    d = evaluate_validate_gate(report)

    assert len(d.pending_requests) == 1
    pr = d.pending_requests[0]
    assert "select" in pr.request_type
    assert pr.context["reason"] == "RETRY_SELECT"
    assert pr.context["stage"] == "SELECT"
    assert pr.context["error_issue_count"] == 2
    assert pr.stage == "validate"


def test_deterministic():
    report = _report(False, {"EXECUTE": _errors("EXECUTE", 2), "SELECT": _errors("SELECT", 1)})

    d1 = evaluate_validate_gate(report)
    d2 = evaluate_validate_gate(report)

    assert validate_gate_route(report) == validate_gate_route(report)
    assert d1.passed == d2.passed
    assert d1.model_dump(exclude={"created_at"}) == d2.model_dump(exclude={"created_at"})
