"""Thin helper owning ValidationReport construction for a validation run."""

from __future__ import annotations

from typing import Any, List

from app.contracts.artifacts.provenance import Provenance
from app.contracts.validation.validation_report_contracts import (
    ValidationIssue,
    ValidationReport,
)


def build_validation_report(
    session_id: str,
    checks: List[Any],
    responsible_stage: str,
) -> ValidationReport:
    """Build a ValidationReport from typed checks grouped by responsibility stage.

    Single owner of the ValidationReport model; does not redefine it. Issues
    are attributed to each check's own responsible_stage, falling back to the
    provided ``responsible_stage``.
    """
    issues: list[ValidationIssue] = []
    for check in checks or []:
        stage = str(
            getattr(check, "responsible_stage", responsible_stage) or responsible_stage
        )
        passed = bool(getattr(check, "passed", False))
        check_id = str(
            getattr(check, "violation_id", "")
            or getattr(check, "check_id", "")
            or ""
        )
        code = str(
            getattr(check, "code", "")
            or getattr(check, "check_id", "")
            or ""
        )
        issues.append(
            ValidationIssue(
                stage=stage,
                severity="warning" if passed else "error",
                code=code,
                message=str(getattr(check, "check_name", "") or code or ""),
                detail=getattr(check, "fix_suggestion", None) or None,
                check_id=check_id,
                actual_value=str(getattr(check, "actual_value", "") or ""),
                expected_value=str(getattr(check, "expected_value", "") or ""),
                affected_parcels=list(getattr(check, "affected_parcels", None) or []),
                affected_target_ids=list(getattr(check, "affected_target_ids", None) or []),
                evidence_refs=list(getattr(check, "evidence_refs", None) or []),
                fix_suggestion=str(getattr(check, "fix_suggestion", "") or ""),
            )
        )
    failed = [c for c in checks or [] if not getattr(c, "passed", False)]
    issues_by_stage: dict[str, list[ValidationIssue]] = {}
    for issue in issues:
        if issue.severity == "error":
            issues_by_stage.setdefault(issue.stage, []).append(issue)
    return ValidationReport(
        checks=list(checks or []),
        overall_passed=not failed,
        issues_by_stage=issues_by_stage,
        adjustments=[],
        context_version=session_id,
        artifact_id="validation-report-" + session_id,
        provenance=Provenance(
            source="report_service",
            run_id=session_id,
            module="app.workflow.validation.report_service",
            natural_language_description="VALIDATE aggregate from typed checks",
        ),
    )


__all__ = ["build_validation_report"]
