"""Build the immutable EXECUTE input from an authoritative scenario.

The builder is deliberately pure.  SELECT and the HUMAN approval boundary
may call it, but neither may invent a scenario or mutate the ScenarioSet.  A
scenario that is partial, failed, or absent is never turned into an executable
approval; it remains a diagnostic/deferral result instead.
"""

from __future__ import annotations

from typing import Any, Mapping

from app.contracts.select.approval import ApprovedExecutionInput
from app.contracts.select.scenario import resolve_formal_scenario_member


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


def _selection_decisions(scenario: Any) -> list[Any]:
    """Build one generic resource decision per selected scenario member."""

    from app.contracts.select.selection_decision import SelectionDecision

    features = {
        str(getattr(item, "candidate_id", "")): item
        for item in list(getattr(scenario, "feature_intents", None) or [])
        if str(getattr(item, "candidate_id", "") or "").strip()
    }
    decisions: list[SelectionDecision] = []
    for selection in list(getattr(scenario, "target_selections", None) or []):
        for candidate_id in list(getattr(selection, "candidate_ids", None) or []):
            feature = features.get(str(candidate_id))
            if feature is None:
                continue
            resource_refs = list(getattr(feature, "resource_refs", None) or [])
            representation_refs = list(getattr(feature, "representation_refs", None) or [])
            geometry_refs = list(getattr(feature, "source_refs", None) or [])
            decisions.append(SelectionDecision(
                selection_ref=f"selection:{selection.target_id}:{candidate_id}",
                target_ref=str(selection.target_id),
                entity_ref=str((getattr(feature, "entity_refs", None) or [""])[0] or ""),
                part_ref=str(getattr(feature, "part_ref", "") or ""),
                representation_ref=str((representation_refs or [""])[0]),
                resource_ref=str((resource_refs or [""])[0]),
                geometry_ref=str((geometry_refs or [candidate_id])[0]),
                operation=str(getattr(selection, "operation", "select") or "select"),
                required_capability=str(getattr(selection, "required_capability", "read") or "read"),
                evidence_refs=list(getattr(feature, "evidence_refs", None) or []),
            ))
    return decisions


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
    selection_decision_set_ref: Any = None,
    selection_decision_set_digest: str = "",
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
    if str(getattr(certificate, "status", "") or "") != "feasible":
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
        from app.modules.execute.plan_digest import execution_plan_semantic_digest

        execution_plan_digest = execution_plan_semantic_digest(execution_plan)
    if approval_status in {"auto", "human_approved"} and not str(execution_plan_digest).strip():
        return None
    resolved_decision_set_ref = _value(
        selection_decision_set_ref,
        "descriptor_digest",
        "digest",
    )
    if not resolved_decision_set_ref or not str(selection_decision_set_digest).strip():
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
    approved_decisions = list(
        getattr(execution_plan, "selection_decisions", None) or []
    )
    if not approved_decisions:
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
        selection_decision_set_ref=resolved_decision_set_ref,
        selection_decision_set_digest=str(selection_decision_set_digest),
        target_ids=target_ids,
        candidate_ids=_selected_candidate_ids(scenario),
        selection_decisions=approved_decisions,
        context_ref=refs,
        bundle_snapshot_digest=str(bundle_snapshot_digest or ""),
        approval_status=approval_status,
        approved_by=str(approved_by or ""),
        approval_revision=max(1, int(approval_revision or 1)),
        approval_reason=str(approval_reason or ""),
    )


__all__ = ["build_approved_execution_input"]
