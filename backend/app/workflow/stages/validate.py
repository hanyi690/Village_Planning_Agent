"""VALIDATE stage service with checksum-bound, target-level repair directives."""

from __future__ import annotations

from typing import Any, Dict

from app.workflow.stage_adapter import persist_stage_artifact
from app.workflow.stages.support import (
    _adopt_context,
    _evaluate_progress_gate,
    _load_ref_artifact,
    _pass_gate,
    _require_context,
    _retry_patch,
    _run_id,
    stage_completion_patch,
)

_RETRY_ROUTE_BY_STAGE = {
    "EXECUTE": "RETRY_EXECUTE",
    "SELECT": "RETRY_SELECT",
    "GROUND": "RETRY_GROUND",
    "L3": "RETRY_L3",
    "TARGET_PROJECTION": "RETRY_TARGET_PROJECTION",
}

_RECOMPUTE_TARGET_BY_STAGE = {
    "EXECUTE": "execute",
    "SELECT": "select",
    "GROUND": "ground",
    "L3": "l3",
    "TARGET_PROJECTION": "target_projection",
}


def _to_typed(data: Any, cls: type) -> Any:
    if data is None or isinstance(data, cls):
        return data
    if isinstance(data, dict):
        try:
            return cls(**data)
        except Exception:
            return data
    return data


def _next_action_forward(target_stage: str) -> Dict[str, Any]:
    return {"type": "forward", "target_stage": target_stage}


def _next_action_recompute(responsible_stage: str, impact: Any) -> Dict[str, Any]:
    return {
        "type": "recompute",
        "target_stage": _RECOMPUTE_TARGET_BY_STAGE.get(
            responsible_stage, responsible_stage.lower()
        ),
        "responsible_stage": responsible_stage,
        "repair_impact_status": str(getattr(impact, "status", "")),
        "rerun_stages": list(getattr(impact, "rerun_stages", None) or []),
        "directive_ids": list(getattr(impact, "directive_ids", None) or []),
    }


def _next_action_human(
    status: str,
    code: str,
    message: str,
) -> Dict[str, Any]:
    return {
        "type": "human_required",
        "status": status,
        "code": code,
        "message": message,
    }


def _override_gate_route(gate: Any, route: str, reason: str) -> Any:
    """Force a typed, non-approving route on the gate the graph routes on."""
    if hasattr(gate, "model_copy"):
        return gate.model_copy(update={"feedback_route": route, "route_reason": reason, "passed": False})
    gate = dict(gate)
    gate.update({"feedback_route": route, "route_reason": reason, "passed": False})
    return gate


def _l3_revision_patch(program: Any, target_ids: list[str]) -> Dict[str, Any] | None:
    claim_dimensions = {
        str(claim.claim_id): str(claim.dimension_key)
        for claim in list(getattr(program, "claims", None) or [])
        if str(getattr(claim, "claim_id", "")) and str(getattr(claim, "dimension_key", ""))
    }
    dimensions = sorted({
        claim_dimensions[claim_ref]
        for intervention in list(getattr(program, "interventions", None) or [])
        if str(getattr(intervention, "target_id", "") or getattr(intervention, "intervention_id", ""))
        in set(target_ids)
        for claim_ref in list(getattr(intervention, "claim_refs", None) or [])
        if claim_ref in claim_dimensions
    })
    if not dimensions:
        return None
    return {
        "phase": "layer3",
        "need_revision": True,
        "is_revision": True,
        "revision_target_dimensions": dimensions,
        "revision_impact_tree": {"0": dimensions},
        "revision_completed_dims": {},
        "revision_feedback": "VALIDATE typed source-contract repair",
        "layer_just_completed": None,
    }


def _auto_defer_blocked_targets(
    state: Dict[str, Any],
    compilation: Any,
    impact: Any,
    working_state: Dict[str, Any],
    *,
    load_ref: Any = None,
    persist: Any = None,
) -> Dict[str, Any] | None:
    """Auto-defer a blocked VALIDATE compilation to enable partial delivery.

    No deterministic repair path exists for the findings: defer the affected
    targets into a typed DeferralLedger and revise the ExecutionPlan so
    RECONCILE/DELIVER treat them as deferred (partial delivery) instead of
    blocking the whole run on HUMAN.  Returns None when there are no
    deferrable target ids (integrity/lineage failures still fail closed).
    """
    if load_ref is None:
        load_ref = _load_ref_artifact
    if persist is None:
        persist = persist_stage_artifact

    reason = str(impact.reason or "validation repair is unresolved")
    defer_ids = sorted({
        str(target_id)
        for item in compilation.unresolved
        for target_id in item.target_ids
        if str(target_id).strip()
    })
    if not defer_ids:
        return None
    # Fail closed when any unresolved finding has no target lineage: auto-defer
    # must never silently mask integrity/lineage failures by force-passing the
    # gate while those blockers remain.
    if any(not getattr(item, "target_ids", None) for item in compilation.unresolved):
        return None

    from app.contracts.artifacts.deferral_contracts import DeferralLedger
    from app.contracts.workflow.execution_plan_contracts import ExecutionPlan
    from app.domain.delivery.deferral_ledger import append_ledger, build_target_deferrals
    from app.domain.materialization.plan_builder import defer_plan_tasks

    existing_ledger = load_ref(state, "deferral_ledger", DeferralLedger)
    ledger = append_ledger(
        existing_ledger,
        build_target_deferrals(
            defer_ids,
            reason="validate_auto_defer:no_repair_policy",
            source_refs=("artifact:validation_report",),
            decided_by="validate",
            rationale=reason,
        ),
    )
    output_refs: Dict[str, Any] = {}
    patch: Dict[str, Any] = {}
    ledger_ref = persist(working_state, "validate", "DeferralLedger", ledger)
    if ledger_ref:
        output_refs["deferral_ledger"] = ledger_ref
        patch["deferral_ledger"] = ledger.model_dump(mode="json")
    plan = load_ref(state, "execution_plan", ExecutionPlan)
    if plan is not None:
        revised_plan = defer_plan_tasks(
            plan, defer_ids, review_id="validate-auto-defer"
        )
        plan_ref = persist(working_state, "validate", "ExecutionPlan", revised_plan)
        if plan_ref:
            output_refs["execution_plan"] = plan_ref
    patch["auto_deferred_target_ids"] = defer_ids
    return {
        "gate": _pass_gate("validate").model_copy(update={
            "feedback_route": "PASS",
            "route_reason": f"auto_deferred_targets:{len(defer_ids)}",
        }),
        "next_action": _next_action_forward("reconcile"),
        "output_refs": output_refs,
        "patch": patch,
    }

async def validate_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Validate the immutable EXECUTE outputs and emit a typed gate + next_action."""
    from app.domain.validation.validate import validate_aggregate
    from app.domain.validation.validate_gate import evaluate_validate_gate
    from app.contracts.workflow.parse_contracts import SpatialPlanningIntent
    from app.contracts.spatial.planned_state_contracts import PlannedState
    from app.contracts.spatial.parcel_change_contracts import ParcelChangeSet
    from app.contracts.workflow.parse_result_contracts import IntentCompilationResult
    from app.contracts.domain.selection_contracts import SiteSelectionDecision
    from app.contracts.workflow.execution_plan_contracts import ExecutionPlan, ExecutionResult
    from app.contracts.planning.scenario import PlanningScenario
    from app.contracts.spatial.grounding_contracts import GroundingResult

    retry_patch = _retry_patch(state, "validate")
    context = await _require_context(state)
    planned_state = None
    changeset = None
    intent = _load_ref_artifact(state, "target_projection", IntentCompilationResult)
    plan_intent = _to_typed(getattr(intent, "typed_intent", None) or intent, SpatialPlanningIntent)
    selection = _load_ref_artifact(state, "site_selection", SiteSelectionDecision)
    execution_plan = _load_ref_artifact(state, "execution_plan", ExecutionPlan)
    execution_result = _load_ref_artifact(state, "execution_result", ExecutionResult)
    scenario = _load_ref_artifact(state, "planning_scenario", PlanningScenario)
    grounding = _load_ref_artifact(state, "grounding_result", GroundingResult)
    bundle_snapshot_digest = ""
    workspace = getattr(context, "workspace", None)
    bundle = getattr(workspace, "_bundle", None)
    if bundle is not None and hasattr(bundle, "spatial_snapshot_digest"):
        try:
            bundle_snapshot_digest = str(bundle.spatial_snapshot_digest() or "")
        except Exception:
            bundle_snapshot_digest = ""
    if execution_result is not None:
        from app.workflow.stages.support import _load_embedded_artifact

        planned_state = _load_embedded_artifact(state, execution_result.planned_state_ref, PlannedState)
        changeset = _load_embedded_artifact(state, execution_result.parcel_changeset_ref, ParcelChangeSet)
    report = validate_aggregate(
        planned_state,
        changeset,
        plan_intent,
        getattr(context, "constraint_index", None),
        run_id=_run_id(state),
        decision=selection,
        execution_plan=execution_plan,
        execution_result=execution_result,
        bundle_snapshot_digest=bundle_snapshot_digest,
    )
    final_relation_validation = None
    if scenario is not None and getattr(grounding, "problem", None) is not None:
        from app.domain.relations.service import RelationEvaluationContext
        from app.domain.relations.reference_features import (
            resolve_relation_reference_features,
        )
        from app.domain.validation.relation_validation import validate_final_scenario
        from app.domain.validation.validate_checks import check_relation_validation

        reference_resolution = resolve_relation_reference_features(
            context,
            list(getattr(grounding.problem, "constraint_factors", None) or []),
            scenario_id=str(getattr(scenario, "scenario_id", "") or ""),
        )
        evaluator_context = RelationEvaluationContext(
            scenario_id=str(getattr(scenario, "scenario_id", "") or ""),
            metric_crs=str(
                getattr(context, "metric_crs", None)
                or getattr(context, "display_crs", None)
                or "EPSG:3857"
            ),
            networks=(
                getattr(context, "networks", None)
                or getattr(context, "network_snapshots", None)
                or {}
            ),
            demands=(
                getattr(context, "demands", None)
                or getattr(context, "demand_snapshots", None)
                or {}
            ),
            reference_features=reference_resolution.features,
            reference_diagnostics=reference_resolution.diagnostics,
            execution_trace=getattr(context, "execution_trace", None),
        )
        if planned_state is None:
            # Keep the final-validation artifact even when EXECUTE did not
            # produce geometry.  validate_final_scenario emits an explicit
            # missing_planned_state finding and fails closed for DELIVER.
            from app.infrastructure.logging import get_logger

            get_logger("workflow.validate").warning(
                "final relation validation has no PlannedState; recording a failed result"
            )
        final_relation_validation = validate_final_scenario(
            scenario,
            planned_state,
            grounding.problem,
            evaluator_context,
        )
        relation_checks = check_relation_validation(final_relation_validation)
        report.checks.extend(relation_checks)
        from app.contracts.artifacts.validation_report_contracts import ValidationIssue

        for check in relation_checks:
            report.issues_by_stage.setdefault(check.responsible_stage, []).append(
                ValidationIssue(
                    stage=check.responsible_stage,
                    severity="warning" if check.passed else "error",
                    code=check.check_id,
                    message=check.actual_value or check.check_name,
                    detail=check.fix_suggestion,
                    check_id=check.check_id,
                    actual_value=check.actual_value,
                    expected_value=check.expected_value,
                    affected_parcels=list(check.affected_parcels),
                    affected_target_ids=list(check.affected_target_ids),
                    evidence_refs=list(check.evidence_refs),
                    fix_suggestion=check.fix_suggestion,
                )
            )
        report.overall_passed = bool(
            report.overall_passed and all(check.passed for check in relation_checks)
        )
    input_keys = {
        "target_projection", "site_selection", "execution_plan", "execution_result",
        "deferral_ledger",
    }
    input_refs = {
        key: value for key, value in (state.get("artifact_refs") or {}).items() if key in input_keys
    }
    gate = _evaluate_progress_gate(
        evaluate_validate_gate,
        report,
        input_artifact_refs=input_refs,
        previous_gate=state.get("validate_gate"),
    )
    from app.contracts.domain.l3_contracts import PlanningProgram
    from app.domain.validation.repair_directives import compile_validation_report_directives
    from app.domain.validation.repair_impact import analyze_repair_impact

    working_state = dict(state)
    working_state["artifact_refs"] = dict(state.get("artifact_refs") or {})
    ref = persist_stage_artifact(working_state, "validate", "ValidationReport", report)
    working_state["artifact_refs"]["validation_report"] = ref
    compilation = compile_validation_report_directives(
        report,
        source_artifact_key="validation_report",
        source_artifact_ref=ref,
    )
    directives_ref = persist_stage_artifact(
        working_state,
        "validate",
        "RepairDirectiveCompilation",
        compilation,
    )
    working_state["artifact_refs"]["repair_directives"] = directives_ref
    impact = analyze_repair_impact(compilation, working_state["artifact_refs"])
    impact_ref = persist_stage_artifact(
        working_state,
        "validate",
        "RepairImpactPlan",
        impact,
    )
    output_refs = {
        "validation_report": ref,
        "repair_directives": directives_ref,
        "repair_impact": impact_ref,
    }
    if final_relation_validation is not None:
        final_relation_ref = persist_stage_artifact(
            working_state,
            "validate",
            "FinalRelationValidation",
            final_relation_validation,
        )
        if final_relation_ref:
            working_state["artifact_refs"]["final_relation_validation"] = final_relation_ref
            output_refs["final_relation_validation"] = final_relation_ref
    patch: Dict[str, Any] = {
        "repair_directives": compilation.model_dump(mode="json"),
        "repair_impact": impact.model_dump(mode="json"),
    }
    if impact.status == "ready":
        responsible_stage = str(impact.earliest_invalid_stage or "EXECUTE")
        route = _RETRY_ROUTE_BY_STAGE.get(responsible_stage, "HUMAN")
        if responsible_stage == "L3":
            program = _load_ref_artifact(state, "planning_program", PlanningProgram)
            revision_patch = _l3_revision_patch(program, impact.affected_target_ids)
            if revision_patch is None:
                route = "HUMAN"
                gate = _override_gate_route(
                    gate,
                    route,
                    reason="typed_repair_blocked:l3_target_dimension_lineage_missing",
                )
                next_action = _next_action_human(
                    "blocked",
                    "l3_target_dimension_lineage_missing",
                    "L3 repair requires target-to-dimension claim lineage.",
                )
            else:
                route = "RETRY_L3"
                patch.update(revision_patch)
                gate = _override_gate_route(gate, route, reason="typed_repair:L3")
                next_action = _next_action_recompute(responsible_stage, impact)
        else:
            gate = _override_gate_route(
                gate,
                route,
                reason=f"typed_repair:{responsible_stage}",
            )
            next_action = _next_action_recompute(responsible_stage, impact)
    elif impact.status == "noop":
        next_action = _next_action_forward("reconcile")
    else:
        auto = _auto_defer_blocked_targets(
            state, compilation, impact, working_state
        )
        if auto is not None:
            gate = auto["gate"]
            next_action = auto["next_action"]
            output_refs.update(auto["output_refs"])
            patch.update(auto["patch"])
        else:
            reason = str(impact.reason or "validation repair is unresolved")
            gate = _override_gate_route(gate, "HUMAN", reason="typed_repair_blocked")
            next_action = _next_action_human("blocked", "typed_repair_blocked", reason)

    failed_checks = [
        check.model_dump(mode="json")
        for check in report.checks
        if not check.passed
    ]
    next_action_type = str(next_action.get("type") or "")
    if report.overall_passed:
        feedback_status = "passed"
    elif next_action_type == "recompute":
        feedback_status = "iteration_required"
    elif next_action_type == "forward":
        feedback_status = "partial_delivery"
    else:
        feedback_status = "human_required"
    validation_feedback = {
        "status": feedback_status,
        "failed_checks": failed_checks,
        "failed_count": len(failed_checks),
        "affected_target_ids": sorted({
            target_id
            for check in report.checks
            if not check.passed
            for target_id in check.affected_target_ids
            if target_id
        }),
        "affected_parcels": sorted({
            parcel
            for check in report.checks
            if not check.passed
            for parcel in check.affected_parcels
            if parcel
        }),
        "evidence_refs": sorted({
            ref
            for check in report.checks
            if not check.passed
            for ref in check.evidence_refs
            if ref
        }),
        "repair_impact": impact.model_dump(mode="json"),
        "next_action": dict(next_action),
        "feedback_route": str(getattr(gate, "feedback_route", "") or ""),
        "route_reason": str(getattr(gate, "route_reason", "") or ""),
    }

    return {
        **stage_completion_patch(
            state,
            "validate",
            output_refs=output_refs,
            gate=gate,
            context_patch=_adopt_context(state, context),
            retry_patch=retry_patch,
        ),
        "next_action": next_action,
        "validation_feedback": validation_feedback,
        **patch,
    }


__all__ = ["validate_node"]
