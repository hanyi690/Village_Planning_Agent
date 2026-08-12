"""Thin helper owning ValidationReport construction for a validation run."""

from __future__ import annotations

from typing import Any, List

from app.modules.schema.contracts.provenance import Provenance
from app.modules.schema.contracts.validation_report_contracts import (
    ConstraintAdjustment,
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
        check_id = str(getattr(check, "check_id", "") or "")
        issues.append(
            ValidationIssue(
                stage=stage,
                severity="warning" if passed else "error",
                code=check_id,
                message=str(getattr(check, "check_name", "") or check_id or ""),
                detail=getattr(check, "fix_suggestion", None) or None,
                check_id=check_id,
            )
        )
    failed = [c for c in checks or [] if not getattr(c, "passed", False)]
    issues_by_stage: dict[str, list[ValidationIssue]] = {}
    for issue in issues:
        if issue.severity == "error":
            issues_by_stage.setdefault(issue.stage, []).append(issue)
    adjustments = [
        ConstraintAdjustment(
            constraint_id=str(getattr(c, "check_id", "") or ""),
            adjustment_type="relax",
            original_value=getattr(c, "expected_value", None),
            adjusted_value=getattr(c, "actual_value", None),
            reason=str(getattr(c, "fix_suggestion", "") or ""),
            source_check=str(getattr(c, "check_id", "") or ""),
        )
        for c in failed
    ]
    return ValidationReport(
        checks=list(checks or []),
        overall_passed=not failed,
        issues_by_stage=issues_by_stage,
        adjustments=adjustments,
        context_version=session_id,
        artifact_id="validation-report-" + session_id,
        provenance=Provenance(
            source="report_service",
            run_id=session_id,
            module="app.domain.validation.report_service",
            natural_language_description="VALIDATE aggregate from typed checks",
        ),
    )


__all__ = ["build_validation_report"]
