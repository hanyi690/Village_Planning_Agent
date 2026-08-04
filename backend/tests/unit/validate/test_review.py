"""VALIDATE review package builder tests (Wave J Task 4)."""

import json

from app.agent.validate.gate import evaluate_validate_gate
from app.agent.validate.review import build_validate_review_package
from app.modules.schema.contracts.provenance import Provenance
from app.modules.schema.contracts.validation_report_contracts import (
    ValidationCheck,
    ValidationIssue,
    ValidationReport,
)

SECTION_KEYS = [
    "检查摘要",
    "按阶段归因",
    "违规清单",
    "面积守恒",
    "拓扑/重叠/连续性",
    "可达性覆盖",
    "Gate 决定",
    "来源追溯",
]


def _make_check(check_id, passed=True, name="", actual="", expected="", stage="EXECUTE"):
    return ValidationCheck(
        check_id=check_id,
        check_name=name or check_id,
        passed=passed,
        actual_value=actual,
        expected_value=expected,
        responsible_stage=stage,
    )


def _full_checks():
    return [
        _make_check("hard_constraints", stage="SELECT"),
        _make_check("area_conservation", actual="100.0", expected="100.0"),
        _make_check("topology"),
        _make_check("overlap"),
        _make_check("continuity"),
        _make_check("accessibility", stage="SELECT"),
        _make_check("contract_completeness"),
        _make_check("classification_missing"),
    ]


def _passing_report():
    return ValidationReport(checks=_full_checks(), overall_passed=True)


def _report_with_issue(stage, code, message="boom"):
    issue = ValidationIssue(
        stage=stage,
        severity="error",
        code=code,
        message=message,
        check_id=code,
    )
    return ValidationReport(
        checks=_full_checks(),
        overall_passed=False,
        issues_by_stage={stage: [issue]},
    )


def test_sections_present():
    report = _passing_report()
    gate = evaluate_validate_gate(report)
    package = build_validate_review_package(report, gate)
    assert set(package.keys()) == set(SECTION_KEYS)


def test_check_summary():
    checks = _full_checks()
    checks[0] = _make_check("hard_constraints", passed=False, stage="SELECT")
    report = ValidationReport(checks=checks, overall_passed=False)
    gate = evaluate_validate_gate(report)
    package = build_validate_review_package(report, gate)

    summary = package["检查摘要"]
    assert summary["total_checks"] == 8
    assert summary["passed_checks"] == 7
    assert summary["failed_checks"] == 1
    assert summary["overall_passed"] is False
    assert len(summary["checks"]) == 8
    assert summary["checks"][0]["check_id"] == "hard_constraints"
    assert summary["checks"][0]["passed"] is False


def test_stage_attribution():
    report = _report_with_issue("EXECUTE", "overlap")
    gate = evaluate_validate_gate(report)
    package = build_validate_review_package(report, gate)

    attribution = package["按阶段归因"]
    assert "EXECUTE" in attribution
    assert len(attribution["EXECUTE"]) == 1
    entry = attribution["EXECUTE"][0]
    assert entry["code"] == "overlap"
    assert entry["severity"] == "error"
    assert entry["message"] == "boom"


def test_violation_list():
    report = _report_with_issue("EXECUTE", "topology")
    gate = evaluate_validate_gate(report)
    package = build_validate_review_package(report, gate)

    violations = package["违规清单"]
    assert isinstance(violations, list)
    assert len(violations) == 1
    assert violations[0]["code"] == "topology"
    assert violations[0]["check_id"] == "topology"


def test_area_conservation_section():
    report = _passing_report()
    gate = evaluate_validate_gate(report)
    package = build_validate_review_package(report, gate)

    section = package["面积守恒"]
    assert section["passed"] is True
    assert section["actual"] == "100.0"
    assert section["expected"] == "100.0"


def test_topology_overlap_continuity():
    report = _passing_report()
    gate = evaluate_validate_gate(report)
    package = build_validate_review_package(report, gate)

    section = package["拓扑/重叠/连续性"]
    assert set(section.keys()) == {"topology", "overlap", "continuity"}
    assert section["topology"]["passed"] is True
    assert section["overlap"]["passed"] is True
    assert section["continuity"]["passed"] is True


def test_accessibility_section():
    report = _passing_report()
    gate = evaluate_validate_gate(report)
    package = build_validate_review_package(report, gate)

    section = package["可达性覆盖"]
    assert section["passed"] is True


def test_gate_decision_section():
    report = _report_with_issue("SELECT", "accessibility")
    gate = evaluate_validate_gate(report)
    package = build_validate_review_package(report, gate)

    section = package["Gate 决定"]
    assert section["route"] == "RETRY_SELECT"
    assert section["passed"] is False
    assert section["rationale"]

    pass_report = _passing_report()
    pass_gate = evaluate_validate_gate(pass_report)
    pass_package = build_validate_review_package(pass_report, pass_gate)
    assert pass_package["Gate 决定"]["route"] == "PASS"


def test_json_serializable():
    report = _report_with_issue("SELECT", "accessibility")
    gate = evaluate_validate_gate(report)
    package = build_validate_review_package(report, gate)
    json.dumps(package)


def test_provenance():
    prov = Provenance(
        source="validate_aggregate",
        run_id="run-1",
        module="app.agent.validate.aggregate",
    )
    report = ValidationReport(
        checks=_full_checks(),
        overall_passed=True,
        provenance=prov,
    )
    gate = evaluate_validate_gate(report)
    package = build_validate_review_package(report, gate)

    section = package["来源追溯"]
    assert section["source"] == "validate_aggregate"
    assert section["run_id"] == "run-1"
