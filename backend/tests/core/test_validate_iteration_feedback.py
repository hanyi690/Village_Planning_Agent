from __future__ import annotations

from app.contracts.artifacts.validation_report_contracts import (
    ValidationCheck,
    ValidationIssue,
    ValidationReport,
)
from app.domain.validation.validate import _check_to_issue
from app.domain.validation.validate_gate import evaluate_validate_gate
from app.workflow.state import project_workflow_state


def test_validation_issue_preserves_target_parcel_and_evidence_lineage() -> None:
    check = ValidationCheck(
        check_id="hard_constraints",
        violation_id="hard_constraints:road-1:parcel-1",
        code="hard_constraints",
        check_name="硬性约束核查",
        passed=False,
        actual_value="constraint=farmland_protection, overlap_pct=31.4",
        expected_value="selected parcel does not overlap a prohibited constraint",
        responsible_stage="SELECT",
        affected_parcels=["parcel-1"],
        affected_target_ids=["road-1"],
        evidence_refs=["constraint:farmland_protection", "bundle:parcel-1"],
        fix_suggestion="排除违规 BSM 后重新执行选择",
    )

    issue = _check_to_issue(check)

    assert issue.affected_parcels == ["parcel-1"]
    assert issue.affected_target_ids == ["road-1"]
    assert issue.evidence_refs == ["constraint:farmland_protection", "bundle:parcel-1"]
    assert issue.actual_value == check.actual_value
    assert issue.expected_value == check.expected_value
    assert issue.fix_suggestion == check.fix_suggestion


def test_validate_gate_returns_actionable_iteration_context() -> None:
    check = ValidationCheck(
        check_id="hard_constraints",
        violation_id="hard_constraints:road-1:parcel-1",
        code="hard_constraints",
        check_name="硬性约束核查",
        passed=False,
        actual_value="constraint=farmland_protection, overlap_pct=31.4",
        expected_value="selected parcel does not overlap a prohibited constraint",
        responsible_stage="SELECT",
        affected_parcels=["parcel-1"],
        affected_target_ids=["road-1"],
        evidence_refs=["constraint:farmland_protection", "bundle:parcel-1"],
        fix_suggestion="排除违规 BSM 后重新执行选择",
    )
    report = ValidationReport(
        checks=[check],
        overall_passed=False,
        issues_by_stage={
            "SELECT": [
                ValidationIssue(
                    stage="SELECT",
                    severity="error",
                    code=check.code,
                    message=check.actual_value,
                    check_id=check.check_id,
                    affected_parcels=check.affected_parcels,
                    affected_target_ids=check.affected_target_ids,
                    evidence_refs=check.evidence_refs,
                )
            ]
        },
        context_version="ctx-1",
    )

    gate = evaluate_validate_gate(
        report,
        input_artifact_refs={"execution_result": "digest-1"},
    )
    request = gate.pending_requests[0]

    assert gate.feedback_route == "RETRY_SELECT"
    assert gate.evidence_requests == ["bundle:parcel-1", "constraint:farmland_protection"]
    assert request.context["target_ids"] == ["road-1"]
    assert request.context["affected_parcels"] == ["parcel-1"]
    assert request.context["evidence_refs"] == [
        "bundle:parcel-1",
        "constraint:farmland_protection",
    ]
    assert request.context["failed_checks"][0]["affected_target_ids"] == ["road-1"]
    assert request.context["failed_checks"][0]["fix_suggestion"] == (
        "排除违规 BSM 后重新执行选择"
    )


def test_workflow_projection_returns_validation_iteration_feedback() -> None:
    feedback = {
        "status": "iteration_required",
        "failed_count": 1,
        "affected_target_ids": ["road-1"],
        "affected_parcels": ["parcel-1"],
        "evidence_refs": ["constraint:farmland_protection"],
        "next_action": {"type": "recompute", "target_stage": "select"},
    }

    projected = project_workflow_state(
        {
            "session_id": "session-1",
            "validation_feedback": feedback,
        }
    )

    assert projected["validation_feedback"] == feedback
