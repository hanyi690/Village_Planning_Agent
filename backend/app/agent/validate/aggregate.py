"""VALIDATE subgraph — deterministic orchestration of the 8 checks into a typed ValidationReport.

Calls each Task 1 check function, flattens the resulting ValidationCheck list, then
builds a ValidationReport with overall_passed, issues grouped by responsibility stage,
and a Provenance record. No LLM, no KG, no MIP — deterministic only.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, List

from app.agent.validate.checks import (
    check_accessibility,
    check_area_conservation,
    check_classification_missing,
    check_contract_completeness,
    check_continuity,
    check_hard_constraints,
    check_overlap,
    check_topology,
)
from app.modules.schema.contracts.provenance import Provenance
from app.modules.schema.contracts.validation_report_contracts import (
    ValidationCheck,
    ValidationIssue,
    ValidationReport,
)


def _check_id_to_stage(check: ValidationCheck) -> str:
    """Map a check to its issues_by_stage key (the responsible_stage Literal value as-is)."""
    return check.responsible_stage


def _check_to_issue(check: ValidationCheck) -> ValidationIssue:
    stage = _check_id_to_stage(check)
    message = f"{check.check_name}: {check.actual_value}" if check.actual_value else check.check_name
    return ValidationIssue(
        stage=stage,
        severity="error" if not check.passed else "warning",
        code=check.check_id,
        message=message,
        detail=check.fix_suggestion or None,
        check_id=check.check_id,
    )


def validate_aggregate(
    planned_state: Any,
    changeset: Any,
    layout_configs: Any,
    intent: Any,
    constraint_index: Any,
    run_id: str = "",
) -> ValidationReport:
    """Run all 8 VALIDATE checks and aggregate their findings into a ValidationReport."""
    if planned_state is None:
        planned_state = SimpleNamespace(parcels=[], facilities=[])

    all_checks: List[ValidationCheck] = []
    all_checks.extend(check_hard_constraints(planned_state, constraint_index))
    all_checks.extend(check_area_conservation(changeset))
    all_checks.extend(check_topology(layout_configs))
    all_checks.extend(check_overlap(layout_configs))
    all_checks.extend(check_continuity(layout_configs))
    all_checks.extend(check_accessibility(planned_state, intent))
    all_checks.extend(check_contract_completeness(planned_state, changeset, intent))
    all_checks.extend(check_classification_missing(planned_state))

    overall_passed = all(c.passed for c in all_checks)

    issues_by_stage: dict = {}
    for check in all_checks:
        if check.passed:
            continue
        issue = _check_to_issue(check)
        issues_by_stage.setdefault(issue.stage, []).append(issue)

    provenance = Provenance(
        source="validate_aggregate",
        run_id=run_id,
        module="app.agent.validate.aggregate",
        natural_language_description=f"VALIDATE aggregate: {len(all_checks)} checks",
    )

    return ValidationReport(
        checks=all_checks,
        overall_passed=overall_passed,
        issues_by_stage=issues_by_stage,
        adjustments=[],
        provenance=provenance,
    )


__all__ = ["validate_aggregate"]
