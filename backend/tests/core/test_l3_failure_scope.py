from __future__ import annotations

from app.contracts.domain.l3_contracts import PlanningIntervention, PlanningProgram, ProgramIssue
from app.contracts.domain.planning_semantics import FacilityPlanningParameters
from app.domain.program.failure_scope import (
    ClaimDependencyGraph,
    CompileSnapshot,
    classify_failure_scope,
    detect_no_progress,
    error_fingerprint,
)
from app.domain.program.gate import evaluate_l3_gate


def _facility() -> PlanningIntervention:
    return PlanningIntervention(
        intervention_id="facility-1",
        target_id="facility-1",
        name="卫生室",
        planning_role="spatial_intervention",
        project_package_ref="pkg:facility-1",
        claim_refs=["claim:facility-1"],
        category="facility",
        asset_kind="facility",
        execution_mode="spatial",
        expected_output_kind="point",
        facility_parameters=FacilityPlanningParameters(facility_type="clinic"),
    )


def test_semantic_compile_exhausted_is_non_blocking_telemetry() -> None:
    issue = ProgramIssue(
        severity="error",
        code="semantic_compile_exhausted",
        claim_id="claim:bad",
    )

    decision = classify_failure_scope(issue, ClaimDependencyGraph())

    assert decision.blocking is False


def test_repeated_fingerprint_stops_without_progress() -> None:
    previous = CompileSnapshot(
        accepted_claim_ids=frozenset({"accepted"}),
        failure_fingerprints=frozenset({"draft_contract_invalid|linear|"}),
        failed_dependency_scope=frozenset({"bad"}),
    )
    current = CompileSnapshot(
        accepted_claim_ids=frozenset({"accepted"}),
        failure_fingerprints=frozenset({"draft_contract_invalid|linear|"}),
        failed_dependency_scope=frozenset({"bad"}),
    )

    decision = detect_no_progress(previous, current)

    assert decision.stop is True


def test_fingerprint_ignores_claim_id_and_prose() -> None:
    first = "ERROR[relation_subject_type_mismatch] claim-a: axis does not accept connect_network"
    second = "ERROR[relation_subject_type_mismatch] claim-b: axis does not accept connect_network"

    assert error_fingerprint(first) == error_fingerprint(second)


def test_unrelated_quarantined_claim_does_not_block_admitted_intervention() -> None:
    program = PlanningProgram(
        interventions=[_facility()],
        program_issues=[ProgramIssue(
            severity="error",
            code="claim_contract_invalid",
            claim_id="claim:quarantined",
        )],
    )

    decision = evaluate_l3_gate(program)

    assert decision.passed is True
    assert decision.feedback_route is None


def test_admitted_claim_error_keeps_fail_closed_scope() -> None:
    program = PlanningProgram(
        interventions=[_facility()],
        program_issues=[ProgramIssue(
            severity="error",
            code="claim_contract_invalid",
            claim_id="claim:facility-1",
        )],
    )

    decision = evaluate_l3_gate(program)

    assert decision.passed is False
    assert decision.feedback_route == "L3"
    assert decision.pending_requests[0].context["failure_scope"] == "claim"
