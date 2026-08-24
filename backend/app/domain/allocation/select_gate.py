"""Deterministic SELECT gate over ScenarioSet and approval facts."""

from __future__ import annotations

from typing import Any

from app.contracts.planning.approval import ApprovedExecutionInput
from app.contracts.planning.scenario import PlanningScenario, ScenarioSet
from app.contracts.workflow.workflow_contracts import GateDecision, PendingRequest

STAGE = "select"


def _pending_target_ids(problem: Any, scenario: PlanningScenario | None) -> list[str]:
    """Derive target scope from typed completeness/finding facts only."""
    ids: set[str] = set()
    if problem is not None:
        completeness = getattr(problem, "candidate_completeness", None)
        for name in (
            "missing_candidate_target_ids",
            "missing_geometry_target_ids",
            "unresolved_target_ids",
            "candidate_only_target_ids",
            "ambiguous_target_ids",
            "degraded_geometry_target_ids",
        ):
            ids.update(str(item) for item in (getattr(completeness, name, None) or []) if str(item).strip())
        ids.update(
            str(getattr(item, "target_id", ""))
            for item in (getattr(problem, "unresolved", None) or []) + (getattr(problem, "deferred", None) or [])
            if str(getattr(item, "target_id", "") or "").strip()
        )
        ids.update(
            str(getattr(domain, "target_id", ""))
            for domain in (getattr(problem, "target_domains", None) or [])
            if str(getattr(domain, "status", "")) in {"unresolved", "ambiguous", "candidate_only"}
            and str(getattr(domain, "target_id", "") or "").strip()
        )
    if scenario is not None:
        ids.update(
            str(getattr(item, "target_id", ""))
            for item in (getattr(scenario, "findings", None) or [])
            if str(getattr(item, "severity", "warning")) != "info"
            and str(getattr(item, "target_id", "") or "").strip()
        )
    return sorted(ids)


def evaluate_scenario_select_gate(
    scenario_set: ScenarioSet | None,
    scenario: PlanningScenario | None,
    problem: Any,
    *,
    approved_input: ApprovedExecutionInput | None = None,
    input_artifact_refs: dict | None = None,
    previous_gate: Any = None,
    context_version: str = "",
) -> GateDecision:
    """PASS only a complete feasible member with executable approval."""
    issues: list[str] = []
    if scenario_set is None:
        issues.append("scenario_set_missing")
    if scenario is None:
        issues.append("planning_scenario_missing")
    if problem is None or not bool(getattr(problem, "can_solve", False)):
        issues.append("grounded_problem_incomplete")
    if scenario_set is not None:
        certificate = getattr(scenario_set, "solver_certificate", None)
        if str(getattr(certificate, "status", "")) not in {"feasible", "bounded"}:
            issues.append("solver_certificate_not_feasible")
        if not str(getattr(scenario_set, "recommended_scenario_id", "") or ""):
            issues.append("recommended_scenario_missing")
    if scenario is not None:
        if str(getattr(scenario, "status", "")) != "complete":
            issues.append("scenario_not_complete")
        if scenario_set is not None and str(getattr(scenario, "scenario_id", "")) not in {
            str(item) for item in (getattr(scenario_set, "feasible_scenario_ids", None) or [])
        }:
            issues.append("scenario_not_feasible_member")
    if approved_input is None or not approved_input.can_execute:
        issues.append("approval_not_ready")
    refs = dict(input_artifact_refs or {})
    issue_fingerprint = "|".join(sorted(set(issues)))
    if issues:
        target_ids = _pending_target_ids(problem, scenario)
        return GateDecision(
            stage=STAGE,
            passed=False,
            feedback_route="HUMAN",
            pending_requests=[PendingRequest(
                request_id="pr-select-scenario-approval",
                stage=STAGE,
                request_type="scenario_approval_required",
                context={
                    "reasons": sorted(set(issues)),
                    "target_ids": target_ids,
                },
            )],
            context_version=context_version,
            input_artifact_refs=refs,
            issue_fingerprint=issue_fingerprint,
            previous_issue_fingerprint=str(getattr(previous_gate, "issue_fingerprint", "") or ""),
            route_reason="scenario_or_approval_incomplete",
        )
    return GateDecision(
        stage=STAGE,
        passed=True,
        feedback_route=None,
        context_version=context_version,
        input_artifact_refs=refs,
        route_reason="scenario_complete_and_approved",
    )


__all__ = ["evaluate_scenario_select_gate"]
