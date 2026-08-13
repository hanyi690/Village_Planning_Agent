"""VALIDATE stage service with checksum-bound, target-level repair directives."""

from __future__ import annotations

from typing import Any, Dict

from app.workflow.stage_adapter import persist_stage_artifact
from app.workflow.stages.support import (
    _adopt_context,
    _evaluate_progress_gate,
    _load_ref_artifact,
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

    retry_patch = _retry_patch(state, "validate")
    context = await _require_context(state)
    planned_state = None
    changeset = None
    intent = _load_ref_artifact(state, "target_projection", IntentCompilationResult)
    plan_intent = _to_typed(getattr(intent, "typed_intent", None) or intent, SpatialPlanningIntent)
    selection = _load_ref_artifact(state, "site_selection", SiteSelectionDecision)
    execution_plan = _load_ref_artifact(state, "execution_plan", ExecutionPlan)
    execution_result = _load_ref_artifact(state, "execution_result", ExecutionResult)
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
        reason = str(impact.reason or "validation repair is unresolved")
        gate = _override_gate_route(gate, "HUMAN", reason="typed_repair_blocked")
        next_action = _next_action_human("blocked", "typed_repair_blocked", reason)

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
        **patch,
    }


__all__ = ["validate_node"]
