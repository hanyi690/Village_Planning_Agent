"""Build the immutable EXECUTE input from an authoritative scenario.

The builder is deliberately pure.  SELECT and the HUMAN approval boundary
may call it, but neither may invent a scenario or mutate the ScenarioSet.  A
scenario that is partial, failed, or absent is never turned into an executable
approval; it remains a diagnostic/deferral result instead.
"""

from __future__ import annotations

from typing import Any, Mapping

from app.contracts.planning.approval import ApprovedExecutionInput
from app.contracts.planning.scenario import resolve_formal_scenario_member


def _value(ref: Any, *keys: str) -> str:
    if isinstance(ref, Mapping):
        for key in keys:
            value = ref.get(key)
            if value:
                return str(value)
        return ""
    for key in keys:
        value = getattr(ref, key, "")
        if value:
            return str(value)
    return ""


def _selected_candidate_ids(scenario: Any) -> list[str]:
    return sorted(
        {
            str(candidate_id)
            for selection in list(getattr(scenario, "target_selections", None) or [])
            for candidate_id in list(getattr(selection, "candidate_ids", None) or [])
            if str(candidate_id).strip()
        }
    )


def build_approved_execution_input(
    *,
    scenario_set: Any,
    scenario: Any,
    scenario_set_ref: Any,
    scenario_ref: Any,
    planning_program_ref: Any = None,
    grounding_problem_ref: str = "",
    context_ref: Mapping[str, Any] | None = None,
    bundle_snapshot_digest: str = "",
    approval_id: str,
    approval_status: str,
    approved_by: str = "",
    approval_revision: int = 1,
    approval_reason: str = "",
    execution_plan_digest: str = "",
    execution_plan: Any = None,
) -> ApprovedExecutionInput | None:
    """Build an executable approval only for a complete ScenarioSet member."""

    try:
        scenario_set, scenario = resolve_formal_scenario_member(
            scenario_set,
            scenario,
        )
    except (TypeError, ValueError):
        return None
    if str(getattr(scenario, "status", "")) != "complete":
        return None
    scenario_id = str(getattr(scenario, "scenario_id", "") or "")
    if not scenario_id:
        return None
    known_scenarios = {
        str(getattr(item, "scenario_id", "") or "")
        for item in list(getattr(scenario_set, "scenarios", None) or [])
    }
    if known_scenarios and scenario_id not in known_scenarios:
        return None
    feasible_ids = {
        str(item)
        for item in list(getattr(scenario_set, "feasible_scenario_ids", None) or [])
        if str(item).strip()
    }
    if scenario_id not in feasible_ids:
        return None
    certificate = getattr(scenario_set, "solver_certificate", None)
    if certificate is None:
        return None
    if str(getattr(certificate, "status", "") or "") not in {"feasible", "bounded"}:
        return None
    if not str(getattr(certificate, "backend_id", "") or "").strip():
        return None
    if not str(getattr(certificate, "backend_version", "") or "").strip():
        return None
    if getattr(certificate, "backend_certificate", None) is None:
        return None
    if approval_status not in {"auto", "human_approved"}:
        return None
    recommended_id = str(
        getattr(scenario_set, "recommended_scenario_id", "") or ""
    )
    if approval_status == "auto" and scenario_id != recommended_id:
        return None
    if (
        approval_status == "human_approved"
        and scenario_id != recommended_id
        and not str(approval_reason).strip()
    ):
        return None
    if execution_plan is not None:
        from app.domain.materialization.plan_digest import execution_plan_semantic_digest

        execution_plan_digest = execution_plan_semantic_digest(execution_plan)
    if approval_status in {"auto", "human_approved"} and not str(execution_plan_digest).strip():
        return None

    problem_fingerprint = str(
        getattr(scenario, "problem_fingerprint", "")
        or getattr(scenario_set, "problem_fingerprint", "")
        or ""
    )
    if problem_fingerprint != str(
        getattr(scenario_set, "problem_fingerprint", "") or ""
    ):
        return None
    scenario_fingerprint = str(getattr(scenario, "fingerprint", "") or "")
    if not problem_fingerprint or not scenario_fingerprint:
        return None
    refs = {
        str(key): str(value)
        for key, value in dict(context_ref or {}).items()
        if str(value).strip()
    }
    target_ids = sorted(
        {
            str(getattr(selection, "target_id", "") or "")
            for selection in list(getattr(scenario, "target_selections", None) or [])
            if str(getattr(selection, "target_id", "") or "").strip()
        }
    )
    if approval_status == "human_approved" and not str(approved_by).strip():
        return None
    return ApprovedExecutionInput(
        approval_id=str(approval_id),
        scenario_set_ref=_value(scenario_set_ref, "descriptor_digest", "digest")
        or str(getattr(scenario_set, "set_id", "") or ""),
        scenario_id=scenario_id,
        scenario_ref=_value(scenario_ref, "descriptor_digest", "digest") or scenario_id,
        scenario_fingerprint=scenario_fingerprint,
        problem_fingerprint=problem_fingerprint,
        baseline_ref=str(
            getattr(scenario_set, "baseline_ref", "")
            or getattr(scenario, "baseline_ref", "")
            or ""
        ),
        planning_program_ref=_value(planning_program_ref, "descriptor_digest", "digest"),
        grounding_problem_ref=str(grounding_problem_ref or problem_fingerprint),
        execution_plan_digest=str(execution_plan_digest or ""),
        target_ids=target_ids,
        candidate_ids=_selected_candidate_ids(scenario),
        context_ref=refs,
        bundle_snapshot_digest=str(bundle_snapshot_digest or ""),
        approval_status=approval_status,
        approved_by=str(approved_by or ""),
        approval_revision=max(1, int(approval_revision or 1)),
        approval_reason=str(approval_reason or ""),
    )


__all__ = ["build_approved_execution_input"]
