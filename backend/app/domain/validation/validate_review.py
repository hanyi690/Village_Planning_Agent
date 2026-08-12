"""VALIDATE review package builder - plain serializable dict.

Pure function: ValidationReport + GateDecision -> dict. No I/O.
Mirrors the ground/select/execute review convention (Chinese section headers,
pydantic models dumped to JSON-safe values). Deterministic only.
"""
from __future__ import annotations

from typing import Any

from app.contracts.artifacts.validation_report_contracts import (
    ValidationCheck,
    ValidationReport,
)
from app.contracts.workflow.workflow_contracts import GateDecision

_ROUTE_RATIONALE = {
    "PASS": "all validation checks passed",
    "RETRY_EXECUTE": "dominant validation errors attributed to EXECUTE",
    "RETRY_SELECT": "dominant validation errors attributed to SELECT",
    "RETRY_GROUND": "dominant validation errors attributed to GROUND",
    "RETRY_L3": "dominant validation errors attributed to L3",
    "RETRY_TARGET_PROJECTION": "dominant validation errors attributed to target projection",
    "HUMAN": "ambiguous validation errors; human review required",
}


def _check_by_id(
    checks: list[ValidationCheck], check_id: str
) -> ValidationCheck | None:
    for check in checks:
        if check.check_id == check_id:
            return check
    return None


def _check_outcome(check: ValidationCheck | None) -> dict[str, Any]:
    if check is None:
        return {"passed": None, "note": "check not performed"}
    return {
        "passed": check.passed,
        "actual": check.actual_value,
        "expected": check.expected_value,
    }


def _build_check_summary(report: ValidationReport) -> dict[str, Any]:
    checks = report.checks
    passed = sum(1 for c in checks if c.passed)
    return {
        "total_checks": len(checks),
        "passed_checks": passed,
        "failed_checks": len(checks) - passed,
        "overall_passed": report.overall_passed,
        "checks": [
            {
                "check_id": c.check_id,
                "check_name": c.check_name,
                "passed": c.passed,
                "responsible_stage": c.responsible_stage,
            }
            for c in checks
        ],
    }


def _build_stage_attribution(report: ValidationReport) -> dict[str, Any]:
    return {
        stage: [
            {"code": i.code, "severity": i.severity, "message": i.message}
            for i in issues
        ]
        for stage, issues in (report.issues_by_stage or {}).items()
    }


def _build_violation_list(report: ValidationReport) -> list[dict[str, Any]]:
    violations = []
    for issues in (report.issues_by_stage or {}).values():
        violations.extend(issues)
    return [v.model_dump() for v in violations]


def _build_area_conservation(report: ValidationReport) -> dict[str, Any]:
    return _check_outcome(_check_by_id(report.checks, "area_conservation"))


def _build_spatial_checks(report: ValidationReport) -> dict[str, Any]:
    return {
        "topology": _check_outcome(_check_by_id(report.checks, "topology")),
        "overlap": _check_outcome(_check_by_id(report.checks, "overlap")),
        "continuity": _check_outcome(_check_by_id(report.checks, "continuity")),
    }


def _build_accessibility(report: ValidationReport) -> dict[str, Any]:
    return _check_outcome(_check_by_id(report.checks, "accessibility"))


def _build_gate_decision(gate: GateDecision) -> dict[str, Any]:
    route = gate.feedback_route or "PASS"
    return {
        "route": route,
        "passed": gate.passed,
        "pending_requests": [pr.model_dump() for pr in gate.pending_requests],
        "rationale": _ROUTE_RATIONALE.get(route, "route undetermined"),
    }


def _build_provenance(report: ValidationReport) -> dict[str, Any]:
    if report.provenance is None:
        return {}
    return report.provenance.model_dump(mode="json")


def build_validate_review_package(
    report: ValidationReport, gate: GateDecision
) -> dict[str, Any]:
    """Construct the VALIDATE review package content dict (pure, no I/O)."""
    return {
        "检查摘要": _build_check_summary(report),
        "按阶段归因": _build_stage_attribution(report),
        "违规清单": _build_violation_list(report),
        "面积守恒": _build_area_conservation(report),
        "拓扑/重叠/连续性": _build_spatial_checks(report),
        "可达性覆盖": _build_accessibility(report),
        "Gate 决定": _build_gate_decision(gate),
        "来源追溯": _build_provenance(report),
    }


__all__ = ["build_validate_review_package"]
