"""Mechanically project one approved scenario into materializer tasks.

This module is intentionally independent from the retired selection service
and legacy decision contract.  Every spatial binding is copied from the
selected ``PlanningScenario`` and its grounded candidate records; no ranking,
allocator, or route provider is consulted here.
"""

from __future__ import annotations

from typing import Any

from app.contracts.execute.materialization_contracts import TargetAssignment
from app.contracts.select.approval import ApprovedExecutionInput
from app.contracts.select.scenario import PlanningScenario, ScenarioSet
from app.contracts.execute.execution_plan_contracts import (
    ExecutionPlan,
    WorkerTask,
    WorkerType,
)


_TASK_SPECS = (
    ("site_area", "site_area_targets"),
    ("zone", "zone_targets"),
    ("zone", "custom_zone_targets"),
    ("facility", "facilities"),
    ("axis", "development_axes"),
    ("road", "road_targets"),
    ("linear", "linear_targets"),
)


def _value(item: Any, name: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(name, default)
    return getattr(item, name, default)


def _dump(item: Any) -> dict[str, Any]:
    if isinstance(item, dict):
        return dict(item)
    dumper = getattr(item, "model_dump", None)
    if callable(dumper):
        return dict(dumper(mode="json"))
    return dict(vars(item)) if hasattr(item, "__dict__") else {}


def _target_items(intent: Any, field_name: str) -> list[Any]:
    value = _value(intent, field_name, None)
    return list(value or [])


def _worker_type(target_type: str, target: Any) -> WorkerType:
    if _value(target, "execution_mode", "spatial") == "non_spatial":
        return WorkerType.NON_SPATIAL_ACTION
    if target_type == "linear":
        return WorkerType.UTILITY_NETWORK
    if target_type == "road" and str(_value(target, "asset_kind", "road")) != "road":
        return WorkerType.UTILITY_NETWORK
    return {
        "site_area": WorkerType.SITE_AREA_FOOTPRINT,
        "zone": WorkerType.PARCEL_TRANSFORMATION,
        "facility": WorkerType.FACILITY_PLACEMENT,
        "axis": WorkerType.AXIS_CONSTRUCTION,
        "road": WorkerType.ROAD_CONSTRUCTION,
    }[target_type]


def _candidate_index(problem: Any) -> dict[str, Any]:
    return {
        str(_value(item, "candidate_id", "")): item
        for item in list(_value(problem, "candidate_geometries", None) or [])
        if str(_value(item, "candidate_id", "") or "").strip()
    }


def _candidate_binding(candidate_ids: list[str], candidate_by_id: dict[str, Any]) -> dict[str, Any]:
    candidates = [candidate_by_id[item] for item in candidate_ids]
    if len(candidates) == 1:
        candidate = candidates[0]
    else:
        candidate = None
    binding: dict[str, Any] = {
        "candidate_ids": list(candidate_ids),
        "source_refs": sorted({str(ref) for item in candidates for ref in (_value(item, "source_refs", None) or []) if str(ref)}),
        "source_bsms": sorted({str(ref) for item in candidates for ref in (_value(item, "source_bsms", None) or []) if str(ref)}),
        "feature_bsms": sorted({str(ref) for item in candidates for ref in (_value(item, "feature_bsms", None) or []) if str(ref)}),
        "source_feature_ids": sorted({str(ref) for item in candidates for ref in (_value(item, "source_feature_ids", None) or []) if str(ref)}),
        "entity_refs": sorted({str(ref) for item in candidates for ref in (_value(item, "entity_refs", None) or []) if str(ref)}),
        "relation_refs": sorted({str(ref) for item in candidates for ref in (_value(item, "relation_refs", None) or []) if str(ref)}),
        "evidence_refs": sorted({str(ref) for item in candidates for ref in (_value(item, "evidence_refs", None) or []) if str(ref)}),
        "adjacent_parcel_bsms": sorted({str(ref) for item in candidates for ref in (_value(item, "adjacent_parcel_bsms", None) or []) if str(ref)}),
        "adjacency_evidence_refs": sorted({str(ref) for item in candidates for ref in (_value(item, "adjacency_evidence_refs", None) or []) if str(ref)}),
    }
    if candidate is not None:
        binding.update({
            "candidate_id": candidate_ids[0],
            "candidate_geometry_wkt": str(_value(candidate, "wkt", "") or ""),
            "geometry_role": str(_value(candidate, "role", "") or ""),
            "geometry_kind": str(_value(candidate, "kind", "") or ""),
            "crs": str(_value(candidate, "crs", "") or ""),
            "source_binding_ref": str(_value(candidate, "source_binding_ref", "") or ""),
            "l1_snapshot_ref": str(_value(candidate, "l1_snapshot_ref", "") or ""),
            "bundle_snapshot_digest": str(_value(candidate, "bundle_snapshot_digest", "") or ""),
            "availability_status": str(_value(candidate, "availability_status", "unknown") or "unknown"),
            "eligible_area_ha": _value(candidate, "eligible_area_ha", None),
            "excluded_area_ha": _value(candidate, "excluded_area_ha", None),
            "adjacent_parcel_bsms": list(_value(candidate, "adjacent_parcel_bsms", None) or []),
            "adjacency_evidence_refs": list(_value(candidate, "adjacency_evidence_refs", None) or []),
        })
    return binding


def build_execution_plan_draft(
    scenario_set: ScenarioSet,
    scenario: PlanningScenario,
    plan_intent: Any,
    problem: Any,
    *,
    run_id: str = "",
    context_version: str = "",
    context_fingerprint: str = "",
) -> ExecutionPlan:
    """Build an approval-neutral plan from frozen scenario facts only.

    The draft is intentionally built before the approval exists.  SELECT can
    hash this exact draft into ``ApprovedExecutionInput`` and then bind the
    approval metadata in a separate step, avoiding a circular dependency.
    """
    if str(scenario.status) != "complete":
        raise ValueError("approved scenario is not complete")
    if str(scenario.problem_fingerprint) != str(scenario_set.problem_fingerprint):
        raise ValueError("approved scenario problem fingerprint is stale")

    candidate_by_id = _candidate_index(problem)
    selections = {
        str(item.target_id): list(item.candidate_ids)
        for item in list(scenario.target_selections or [])
    }
    # A scoped SELECT child problem is authoritative for the formal batch.
    # Targets recorded in its deferral ledger are intentionally outside this
    # execution plan; requiring a scenario member for them would reintroduce
    # the parent problem's unresolved scope after the child solve succeeded.
    deferred_target_ids = {
        str(target_id).strip()
        for target_id in list(_value(problem, "deferred_target_ids", None) or [])
        if str(target_id).strip()
    }
    approved_candidates = {
        str(candidate_id)
        for selection in list(scenario.target_selections or [])
        for candidate_id in list(selection.candidate_ids or [])
    }
    tasks: list[WorkerTask] = []
    for target_type, field_name in _TASK_SPECS:
        for target in _target_items(plan_intent, field_name):
            target_id = str(_value(target, "target_id", "") or "")
            if not target_id:
                continue
            if target_id in deferred_target_ids:
                continue
            candidate_ids = [str(item) for item in selections.get(target_id, []) if str(item).strip()]
            spatial = bool(_value(target, "requires_spatial", True))
            if spatial and not candidate_ids:
                raise ValueError(f"approved scenario has no member for target {target_id}")
            missing = [item for item in candidate_ids if item not in candidate_by_id]
            if missing:
                raise ValueError(f"approved candidate geometry is missing: {', '.join(missing)}")
            payload = _dump(target)
            worker_type = _worker_type(target_type, target)
            if worker_type in {WorkerType.UTILITY_NETWORK}:
                raise ValueError(f"approved task capability is not materializer-only: {target_id}")
            # A selected member is an independently materializable unit.  Do
            # not collapse all_members/choose_subset into the first geometry:
            # every approved candidate must produce its own task and carry its
            # own feature/evidence lineage.
            task_candidate_ids = candidate_ids or [""]
            for candidate_id in task_candidate_ids:
                member_ids = [candidate_id] if candidate_id else []
                binding = {**payload, **_candidate_binding(member_ids, candidate_by_id)}
                assignment = TargetAssignment(
                    target_id=target_id,
                    target_type=target_type,
                    status="placed" if spatial else "ready",
                    expected_output_kind=str(_value(target, "expected_output_kind", "parcel") or "parcel"),
                    target_binding=binding,
                    selected_bsm=(binding.get("source_bsms") or [""])[0],
                    selected_bsms=list(binding.get("source_bsms") or []),
                    relation_refs=list(_value(target, "relation_refs", None) or []),
                    evidence_refs=list(binding.get("evidence_refs") or []),
                    availability_status=str(binding.get("availability_status") or "unknown"),
                    eligible_area_ha=binding.get("eligible_area_ha"),
                    excluded_area_ha=binding.get("excluded_area_ha"),
                    adjacent_parcel_bsms=list(binding.get("adjacent_parcel_bsms") or []),
                    adjacency_evidence_refs=list(binding.get("adjacency_evidence_refs") or []),
                )
                task_suffix = f":{candidate_id}" if len(task_candidate_ids) > 1 else ""
                tasks.append(WorkerTask(
                    task_id=f"{worker_type.value}:{target_id}{task_suffix}",
                    worker_type=worker_type,
                    target_id=target_id,
                    target_type=target_type,
                    expected_output_kind=assignment.expected_output_kind,
                    assignment=assignment,
                    payload={"target_id": target_id},
                    required_capability=worker_type.value,
                    scenario_id=str(scenario.scenario_id),
                    candidate_id=candidate_id,
                    candidate_ids=member_ids,
                    relation_ids=list(assignment.relation_refs or []),
                    feature_ids=list(binding.get("feature_ids") or []),
                    source_feature_ids=list(binding.get("source_feature_ids") or []),
                    entity_refs=list(binding.get("entity_refs") or []),
                    relation_refs=list(assignment.relation_refs or binding.get("relation_refs") or []),
                    target_binding=binding,
                    feature_bsms=list(binding.get("feature_bsms") or []),
                    evidence_refs=list(binding.get("evidence_refs") or []),
                    l1_snapshot_ref=str(binding.get("l1_snapshot_ref") or ""),
                    bundle_snapshot_digest=str(binding.get("bundle_snapshot_digest") or ""),
                    source_binding_ref=str(binding.get("source_binding_ref") or ""),
                    availability_status=str(binding.get("availability_status") or "unknown"),
                    eligible_area_ha=binding.get("eligible_area_ha"),
                    excluded_area_ha=binding.get("excluded_area_ha"),
                    adjacent_parcel_bsms=list(binding.get("adjacent_parcel_bsms") or []),
                    adjacency_evidence_refs=list(binding.get("adjacency_evidence_refs") or []),
                ))
    return ExecutionPlan(
        schema_version="2.0",
        plan_id=f"execute-{run_id or 'current'}",
        approved_input_fingerprint="",
        scenario_id=str(scenario.scenario_id),
        scenario_fingerprint=str(scenario.fingerprint),
        problem_fingerprint=str(scenario.problem_fingerprint),
        candidate_ids=sorted(approved_candidates),
        worker_tasks=tasks,
        context_version=context_version,
        context_fingerprint=context_fingerprint,
    )


def bind_approved_execution_plan(
    draft: Any,
    approved_input: ApprovedExecutionInput,
    scenario_set: ScenarioSet,
    scenario: PlanningScenario,
) -> Any:
    """Bind only immutable approval metadata to a previously hashed draft."""
    from app.modules.execute.plan_digest import execution_plan_semantic_digest

    if not approved_input.can_execute:
        raise ValueError("approved execution input is not executable")
    approved_input.assert_matches(
        scenario_set,
        scenario,
        scenario_set_ref=approved_input.scenario_set_ref,
    )
    expected_digest = execution_plan_semantic_digest(draft)
    if approved_input.execution_plan_digest != expected_digest:
        raise ValueError("approved input execution plan digest does not match draft")
    bound = draft.model_copy(update={
        "approved_input_fingerprint": approved_input.fingerprint,
        "scenario_id": approved_input.scenario_id,
    })
    approved_input.assert_execution_plan_matches(bound)
    return bound


__all__ = ["build_execution_plan_draft", "bind_approved_execution_plan"]
