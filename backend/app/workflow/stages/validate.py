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


def _descriptor_digest(value: Any) -> str:
    """Read an artifact descriptor digest from dict or typed refs."""
    if isinstance(value, dict):
        return str(value.get("descriptor_digest") or value.get("digest") or "")
    return str(
        getattr(value, "descriptor_digest", "")
        or getattr(value, "digest", "")
        or ""
    )


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


async def validate_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Validate the immutable EXECUTE outputs and emit a typed gate + next_action."""
    from app.workflow.validation.validate import validate_aggregate
    from app.workflow.validation.validate_gate import evaluate_validate_gate
    from app.contracts.target_projection.parse_contracts import SpatialPlanningIntent
    from app.contracts.execute.planned_state_contracts import PlannedState
    from app.contracts.execute.parcel_change_contracts import ParcelChangeSet
    from app.contracts.target_projection.parse_result_contracts import IntentCompilationResult
    from app.contracts.execute.execution_plan_contracts import ExecutionPlan, ExecutionResult
    from app.contracts.select.scenario import PlanningScenario, ScenarioSet
    from app.contracts.validation.validation_certificate_contracts import ValidationCertificate
    from app.contracts.ground.grounding_contracts import GroundingResult
    from app.contracts.ground.grounded_problem import GroundedPlanningProblem

    retry_patch = _retry_patch(state, "validate")
    context = await _require_context(state)
    planned_state = None
    changeset = None
    intent = _load_ref_artifact(state, "target_projection", IntentCompilationResult)
    plan_intent = _to_typed(getattr(intent, "typed_intent", None) or intent, SpatialPlanningIntent)
    execution_plan = _load_ref_artifact(state, "execution_plan", ExecutionPlan)
    execution_result = _load_ref_artifact(state, "execution_result", ExecutionResult)
    scenario = _load_ref_artifact(state, "planning_scenario", PlanningScenario)
    scenario_set = _load_ref_artifact(state, "scenario_set", ScenarioSet)
    grounding = _load_ref_artifact(state, "grounding_result", GroundingResult)
    scoped_problem = _load_ref_artifact(
        state, "scoped_grounding_problem", GroundedPlanningProblem
    )
    planning_problem = scoped_problem or getattr(grounding, "problem", None)
    context_ref = dict(state.get("context_ref") or {})
    bundle_snapshot_digest = str(
        context_ref.get("snapshot_digest")
        or context_ref.get("bundle_snapshot_digest")
        or ""
    )
    workspace = getattr(context, "workspace", None)
    bundle = getattr(workspace, "_bundle", None)
    if not bundle_snapshot_digest and bundle is not None and hasattr(bundle, "spatial_snapshot_digest"):
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
        execution_plan=execution_plan,
        execution_result=execution_result,
        bundle_snapshot_digest=bundle_snapshot_digest,
    )
    final_relation_validation = None
    if scenario is not None and planning_problem is not None:
        from app.spatial.relations.service import RelationEvaluationContext
        from app.spatial.relations.reference_features import (
            resolve_relation_reference_features,
        )
        from app.workflow.validation.relation_validation import validate_final_scenario
        from app.workflow.validation.validate_checks import check_relation_validation

        reference_resolution = resolve_relation_reference_features(
            context,
            list(getattr(planning_problem, "constraint_factors", None) or []),
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
            planning_problem,
            evaluator_context,
        )
        relation_checks = check_relation_validation(final_relation_validation)
        report.checks.extend(relation_checks)
        from app.contracts.validation.validation_report_contracts import ValidationIssue

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
        "target_projection", "scenario_set", "planning_scenario", "approved_execution_input", "execution_plan", "execution_result",
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
    from app.contracts.l3.l3_contracts import PlanningProgram
    from app.workflow.validation.repair_directives import compile_validation_report_directives
    from app.workflow.validation.repair_impact import analyze_repair_impact

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
            "FinalScenarioValidation",
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
        # A reduced scope needs a new scoped planning problem, ScenarioSet,
        # and approval.  VALIDATE must not auto-defer and forward the old
        # approval as a partial formal execution.
        reason = str(impact.reason or "validation repair is unresolved")
        gate = _override_gate_route(gate, "HUMAN", reason="typed_repair_blocked")
        next_action = _next_action_human("blocked", "typed_repair_blocked", reason)

    certificate_failed_checks = [check for check in report.checks if not check.passed]
    certificate_status = (
        "passed"
        if report.overall_passed
        else ("partial" if str(next_action.get("type") or "") == "forward" else "blocked")
    )
    execution_result_ref = (state.get("artifact_refs") or {}).get("execution_result")
    execution_result_digest = str(
        execution_result_ref.get("descriptor_digest")
        if isinstance(execution_result_ref, dict)
        else getattr(execution_result_ref, "descriptor_digest", "")
    )
    approved_ref = (state.get("artifact_refs") or {}).get("approved_execution_input")
    approved_digest = str(
        approved_ref.get("descriptor_digest")
        if isinstance(approved_ref, dict)
        else getattr(approved_ref, "descriptor_digest", "")
    )
    certificate = ValidationCertificate(
        certificate_id=f"validation-certificate:{_run_id(state)}:{getattr(execution_result, 'artifact_id', '') or 'current'}",
        approved_input_ref=approved_digest,
        execution_result_ref=execution_result_digest or "execution-result:missing",
        planned_state_ref=_descriptor_digest(
            getattr(execution_result, "planned_state_ref", None)
        ),
        parcel_changeset_ref=_descriptor_digest(
            getattr(execution_result, "parcel_changeset_ref", None)
        ),
        planned_state_fingerprint=str(
            getattr(planned_state, "fingerprint", "")
            or getattr(planned_state, "artifact_id", "")
            or ""
        ),
        scenario_id=str(getattr(scenario, "scenario_id", "") or ""),
        scenario_fingerprint=str(getattr(scenario, "fingerprint", "") or ""),
        scenario_set_fingerprint=str(getattr(scenario_set, "fingerprint", "") or ""),
        baseline_ref=str(getattr(scenario, "baseline_ref", "") or ""),
        selected_target_count=len(list(getattr(scenario, "target_selections", None) or [])),
        materialized_target_count=len({
            str(getattr(item, "target_id", "") or "")
            for item in list(getattr(execution_result, "task_results", None) or [])
            if str(getattr(item, "status", "") or "") == "succeeded"
            and str(getattr(item, "target_id", "") or "")
        }),
        selected_target_ids=sorted({
            str(getattr(item, "target_id", "") or "")
            for item in list(getattr(scenario, "target_selections", None) or [])
            if str(getattr(item, "target_id", "") or "")
        }),
        materialized_target_ids=sorted({
            str(getattr(item, "target_id", "") or "")
            for item in list(getattr(execution_result, "task_results", None) or [])
            if str(getattr(item, "status", "") or "") == "succeeded"
            and str(getattr(item, "target_id", "") or "")
        }),
        context_version=str(getattr(context, "version", "") or _context_version(state)),
        bundle_snapshot_digest=bundle_snapshot_digest,
        status=certificate_status,
        check_ids=[str(check.check_id) for check in report.checks],
        passed_check_ids=[str(check.check_id) for check in report.checks if check.passed],
        blocking_issue_codes=[str(check.code or check.check_id) for check in certificate_failed_checks],
        issue_count=len(certificate_failed_checks),
        atomic_execution=(
            execution_result is not None
            and str(getattr(execution_result, "atomic_commit_status", "aborted")) == "committed"
        ),
        diagnostics=[
            str(getattr(issue, "message", "") or "")
            for issues in report.issues_by_stage.values()
            for issue in issues
            if getattr(issue, "message", "")
        ],
    )
    certificate_ref = persist_stage_artifact(
        working_state, "validate", "ValidationCertificate", certificate
    )
    working_state["artifact_refs"]["validation_certificate"] = certificate_ref
    output_refs["validation_certificate"] = certificate_ref

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
