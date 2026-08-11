"""VALIDATE subgraph — deterministic orchestration of the 9 checks into a typed ValidationReport.

Calls each Task 1 check function, flattens the resulting ValidationCheck list, then
builds a ValidationReport with overall_passed, issues grouped by responsibility stage,
and a Provenance record. No LLM, no KG, no MIP — deterministic only.
"""

from __future__ import annotations

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
    check_traceability,
)
from app.modules.schema.contracts.provenance import Provenance
from app.modules.schema.contracts.validation_report_contracts import (
    ConstraintAdjustment,
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
    decision: Any = None,
    execution_plan: Any = None,
    execution_outcome: Any = None,
) -> ValidationReport:
    """Run all 9 VALIDATE checks and aggregate their findings into a ValidationReport."""
    if planned_state is None:
        missing_check = ValidationCheck(
            check_id="missing_planned_state",
            check_name="planned_state presence",
            passed=False,
            actual_value="None",
            expected_value="non-null PlannedState",
            responsible_stage="EXECUTE",
            fix_suggestion="EXECUTE produced no planned_state; retry EXECUTE",
        )
        return ValidationReport(
            checks=[missing_check],
            overall_passed=False,
            issues_by_stage={"EXECUTE": [_check_to_issue(missing_check)]},
            adjustments=[],
            provenance=Provenance(
                source="validate_aggregate", run_id=run_id,
                module="app.agent.validate.aggregate",
                natural_language_description="blocked: planned_state is None",
            ),
        )

    all_checks: List[ValidationCheck] = []
    all_checks.extend(check_hard_constraints(planned_state, constraint_index))
    all_checks.extend(check_area_conservation(changeset))
    all_checks.extend(check_topology(planned_state))
    all_checks.extend(check_overlap(planned_state))
    all_checks.extend(check_continuity(planned_state))
    all_checks.extend(check_accessibility(planned_state, intent))
    all_checks.extend(check_contract_completeness(
        planned_state,
        changeset,
        intent,
        execution_plan=execution_plan,
    ))
    all_checks.extend(check_classification_missing(planned_state))
    all_checks.extend(check_traceability(
        changeset,
        intent,
        decision=decision,
        execution_plan=execution_plan,
        execution_outcome=execution_outcome,
    ))

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

    adjustments = [
        ConstraintAdjustment(
            constraint_id=check.check_id,
            adjustment_type="relax",
            original_value=check.expected_value,
            adjusted_value=check.actual_value,
            reason=check.fix_suggestion or "",
            source_check=check.check_id,
        )
        for check in all_checks
        if not check.passed
    ]

    return ValidationReport(
        checks=all_checks,
        overall_passed=overall_passed,
        issues_by_stage=issues_by_stage,
        adjustments=adjustments,
        provenance=provenance,
    )


__all__ = ["validate_aggregate"]
