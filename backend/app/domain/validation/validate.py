"""VALIDATE subgraph — deterministic orchestration of the 9 checks into a typed ValidationReport.

Calls each Task 1 check function, flattens the resulting ValidationCheck list, then
builds a ValidationReport with overall_passed, issues grouped by responsibility stage,
and a Provenance record. No LLM, no KG, no MIP — deterministic only.
"""

from __future__ import annotations

from typing import Any, List

from app.domain.validation.validate_checks import (
    check_accessibility,
    check_area_conservation,
    check_candidate_materialization,
    check_bundle_snapshot_lineage,
    check_classification_missing,
    check_contract_completeness,
    check_continuity,
    check_hard_constraints,
    check_overlap,
    check_topology,
    check_traceability,
    check_worker_failures,
)
from app.contracts.artifacts.provenance import Provenance
from app.contracts.artifacts.validation_report_contracts import (
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
        actual_value=check.actual_value,
        expected_value=check.expected_value,
        affected_parcels=list(check.affected_parcels),
        affected_target_ids=list(check.affected_target_ids),
        evidence_refs=list(check.evidence_refs),
        fix_suggestion=check.fix_suggestion,
    )


def validate_aggregate(
    planned_state: Any,
    changeset: Any,
    intent: Any,
    constraint_index: Any,
    run_id: str = "",
    decision: Any = None,
    execution_plan: Any = None,
    execution_result: Any = None,
    bundle_snapshot_digest: str = "",
) -> ValidationReport:
    """Validate typed execution outputs; render layers are not fact inputs."""
    if planned_state is None:
        typed_worker_checks = check_worker_failures(execution_result)
        if typed_worker_checks:
            issues_by_stage: dict[str, list[ValidationIssue]] = {}
            for check in typed_worker_checks:
                issue = _check_to_issue(check)
                issues_by_stage.setdefault(issue.stage, []).append(issue)
            return ValidationReport(
                checks=typed_worker_checks,
                overall_passed=False,
                issues_by_stage=issues_by_stage,
                adjustments=[],
                provenance=Provenance(
                    source="validate_aggregate",
                    run_id=run_id,
                    module="app.domain.validation.validate",
                    natural_language_description=(
                        "planned_state blocked by target-bound worker failures"
                    ),
                ),
            )
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
                module="app.domain.validation.validate",
                natural_language_description="blocked: planned_state is None",
            ),
        )

    all_checks: List[ValidationCheck] = []
    all_checks.extend(check_hard_constraints(planned_state, constraint_index))
    all_checks.extend(check_area_conservation(changeset))
    all_checks.extend(check_topology(planned_state))
    all_checks.extend(check_candidate_materialization(planned_state))
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
        execution_plan,
        execution_result,
    ))
    all_checks.extend(check_worker_failures(execution_result))
    all_checks.extend(check_bundle_snapshot_lineage(
        planned_state,
        execution_plan,
        execution_result,
        bundle_snapshot_digest,
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
        module="app.domain.validation.validate",
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
