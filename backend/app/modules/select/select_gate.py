"""Deterministic SELECT gate over ScenarioSet and approval facts."""

from __future__ import annotations

from typing import Any

from app.contracts.select.approval import ApprovedExecutionInput
from app.contracts.select.scenario import PlanningScenario, ScenarioSet
from app.contracts.select.solver_readiness import SolverReadiness
from app.contracts.workflow.recovery_pointer import RecoveryPointer
from app.contracts.workflow.workflow_contracts import GateDecision, PendingRequest

STAGE = "select"


def _pending_target_ids(
    problem: Any,
    scenario: PlanningScenario | None,
    solver_subproblem_plan: Any = None,
    planning_task_graph: Any = None,
) -> list[str]:
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
    # A target can have a resolved candidate domain and still be blocked by a
    # typed solver prerequisite (for example a missing demand/network input),
    # or by a hard relation whose grounding status is deferred.  These are
    # legitimate SELECT-level deferral candidates.  They must be exposed in
    # the same typed target scope as unresolved geometries; otherwise an
    # unattended HUMAN approval cannot produce an auditable partial delivery.
    if solver_subproblem_plan is not None:
        for subproblem in getattr(solver_subproblem_plan, "subproblems", None) or ():
            if str(getattr(subproblem, "status", "ready")) != "ready":
                ids.update(
                    str(target_id)
                    for target_id in (getattr(subproblem, "target_refs", None) or ())
                    if str(target_id).strip()
                )
    if planning_task_graph is not None:
        for task in getattr(planning_task_graph, "tasks", None) or ():
            if str(getattr(task, "status", "") or "") not in {"blocked", "failed"}:
                continue
            ids.update(
                str(target_id)
                for target_id in (getattr(task, "target_refs", None) or ())
                if str(target_id).strip()
            )
    if problem is not None:
        target_ids = {
            str(getattr(item, "target_id", "") or "").strip()
            for item in (
                list(getattr(problem, "target_domains", None) or [])
                + list(getattr(problem, "candidate_domains", None) or [])
            )
            if str(getattr(item, "target_id", "") or "").strip()
        }
        for factor in getattr(problem, "constraint_factors", None) or ():
            if not bool(getattr(factor, "hard", False)):
                continue
            status = str(getattr(factor, "status", "") or "").strip().lower()
            if status in {"satisfied", "accepted", "pass", "passed"}:
                continue
            subject_ref = str(getattr(factor, "subject_ref", "") or "").strip()
            if subject_ref in target_ids:
                ids.add(subject_ref)
            object_ref = str(getattr(factor, "object_ref", "") or "").strip()
            if (
                object_ref in target_ids
                and str(getattr(factor, "object_ref_kind", "target") or "target")
                == "target"
            ):
                ids.add(object_ref)
    return sorted(ids)


def _artifact_input_refs(input_artifact_refs: dict[str, Any]) -> list[str]:
    """Expose the immutable inputs needed to repair a blocked target."""

    refs: list[str] = []
    for key in (
        "l1_snapshot",
        "planning_program",
        "target_projection",
        "grounding_result",
    ):
        value = input_artifact_refs.get(key)
        if isinstance(value, dict):
            digest = str(
                value.get("digest")
                or value.get("descriptor_digest")
                or ""
            ).strip()
        else:
            digest = str(
                getattr(value, "digest", "")
                or getattr(value, "descriptor_digest", "")
                or ""
            ).strip()
        if digest:
            refs.append(f"{key}:{digest}")
    return refs


def _recovery_for_target(
    target_id: str,
    *,
    issues: list[str],
    input_artifact_refs: dict[str, Any],
    readiness: SolverReadiness | None,
) -> RecoveryPointer:
    """Point one blocked target back to its current grounding inputs."""

    target_blockers = [
        str(ref).strip()
        for ref in (getattr(readiness, "blocker_refs", None) or [])
        if str(ref).strip()
        and (
            target_id in str(ref)
            or not str(ref).strip().startswith("target:")
        )
    ]
    missing = list(dict.fromkeys([
        "candidate_geometry",
        "source_binding",
        *list(issues),
        *target_blockers,
    ]))
    return RecoveryPointer(
        item_id=target_id,
        item_kind="target",
        source_stage="ground",
        return_stage="ground",
        source_artifact_key="target_projection",
        source_artifact_ref=(
            str(
                (input_artifact_refs.get("target_projection") or {}).get("digest", "")
                if isinstance(input_artifact_refs.get("target_projection"), dict)
                else getattr(input_artifact_refs.get("target_projection"), "digest", "")
            ).strip()
        ),
        source_input_refs=_artifact_input_refs(input_artifact_refs),
        missing_requirements=missing,
        expected_artifact_key="grounding_result",
        reason_code="select_target_not_ready",
    )


def evaluate_scenario_select_gate(
    scenario_set: ScenarioSet | None,
    scenario: PlanningScenario | None,
    problem: Any,
    *,
    approved_input: ApprovedExecutionInput | None = None,
    input_artifact_refs: dict | None = None,
    previous_gate: Any = None,
    context_version: str = "",
    solver_subproblem_plan: Any = None,
    planning_task_graph: Any = None,
    readiness: SolverReadiness | None = None,
    selection_decision_set: Any = None,
) -> GateDecision:
    """PASS only a complete feasible member with executable approval."""
    issues: list[str] = []
    if scenario_set is None:
        issues.append("scenario_set_missing")
    if scenario is None:
        issues.append("planning_scenario_missing")
    if problem is None or not bool(getattr(problem, "can_solve", False)):
        issues.append("grounded_problem_incomplete")
    if readiness is not None and not readiness.ready:
        issues.append(f"solver_readiness:{readiness.status}")
    if scenario_set is not None:
        certificate = getattr(scenario_set, "solver_certificate", None)
        certificate_status = str(getattr(certificate, "status", "") or "").strip()
        if certificate_status not in {"feasible"}:
            issues.append({
                "unknown": "solver_certificate_unknown",
                "infeasible": "solver_certificate_infeasible",
                "timeout": "solver_certificate_timeout",
                "bounded": "solver_certificate_not_complete",
            }.get(certificate_status, "solver_certificate_not_ready"))
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
    if selection_decision_set is None:
        issues.append("selection_resource_binding_incomplete")
    if planning_task_graph is not None and any(
        str(getattr(task, "status", "") or "") in {"blocked", "failed"}
        for task in (getattr(planning_task_graph, "tasks", None) or ())
    ):
        issues.append("planning_task_prerequisites_incomplete")
    refs = dict(input_artifact_refs or {})
    issue_fingerprint = "|".join(sorted(set(issues)))
    if issues:
        from app.contracts.target_projection.p1_closure import build_decision_fingerprint

        target_ids = _pending_target_ids(
            problem,
            scenario,
            solver_subproblem_plan,
            planning_task_graph,
        )
        pending_requests: list[PendingRequest] = []
        for target_id in target_ids:
            recovery = _recovery_for_target(
                target_id,
                issues=sorted(set(issues)),
                input_artifact_refs=refs,
                readiness=readiness,
            )
            pending_requests.append(
                PendingRequest(
                    request_id=f"pr-select-target-{target_id}",
                    stage=STAGE,
                    request_type="target_grounding_input_required",
                    context={
                        "reasons": sorted(set(issues)),
                        "target_id": target_id,
                        "target_ids": target_ids,
                        "readiness_status": readiness.status if readiness is not None else "",
                        "readiness_blocker_refs": list(readiness.blocker_refs) if readiness is not None else [],
                        "source_input_refs": recovery.source_input_refs,
                        "expected_artifact_key": recovery.expected_artifact_key,
                        "recovery_fingerprint": recovery.fingerprint,
                        "decision_fingerprint": build_decision_fingerprint(
                            target_ref=target_id,
                            constraint_fingerprint=(
                                readiness.fingerprint if readiness is not None else ""
                            ),
                        ).model_dump(mode="json"),
                    },
                    recovery=recovery,
                )
            )
        if not pending_requests:
            pending_requests.append(
                PendingRequest(
                    request_id="pr-select-scenario-approval",
                    stage=STAGE,
                    request_type="scenario_approval_required",
                    context={
                        "reasons": sorted(set(issues)),
                        "target_ids": target_ids,
                        "readiness_status": readiness.status if readiness is not None else "",
                        "readiness_blocker_refs": list(readiness.blocker_refs) if readiness is not None else [],
                    },
                )
            )
        diagnostic_only = (
            scenario_set is None
            and problem is not None
            and not bool(getattr(problem, "can_solve", False))
        )
        return GateDecision(
            stage=STAGE,
            passed=False,
            feedback_route="END_DIAGNOSTIC" if diagnostic_only else "HUMAN",
            pending_requests=pending_requests,
            context_version=context_version,
            input_artifact_refs=refs,
            issue_fingerprint=issue_fingerprint,
            previous_issue_fingerprint=str(getattr(previous_gate, "issue_fingerprint", "") or ""),
            route_reason=(
                "no_executable_grounded_problem"
                if diagnostic_only
                else "scenario_or_approval_incomplete"
            ),
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
