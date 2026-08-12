"""VALIDATE stage service.

M7 bounded auto-repair loop:
  EXECUTE -> VALIDATE -> diagnose -> BoundedAdjustmentExecutor ->
  earliest-affected-stage recompute -> VALIDATE (max 2 rounds).

Pure stage: builds a ValidationReport from the deterministic checks, asks the
executor for a bounded adjustment, and returns a typed StageCompletion-style
patch whose gate + ``next_action`` tell the graph which stage to recompute (or
that HUMAN review is required).  It never calls workflow nodes directly.
"""

from __future__ import annotations

from typing import Any, Dict

from app.contracts.workflow.repair import (
    AdjustmentExecutionResult,
    ValidationAdjustment,
)
from app.domain.validation.adjustment_executor import BoundedAdjustmentExecutor
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

_LEDGER_KEY = "validation_adjustment_log"
_MAX_ROUNDS = 2

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


def _next_action_recompute(
    responsible_stage: str,
    result: AdjustmentExecutionResult,
    adjustment: ValidationAdjustment | None,
) -> Dict[str, Any]:
    iteration = result.iteration
    return {
        "type": "recompute",
        "target_stage": _RECOMPUTE_TARGET_BY_STAGE.get(
            responsible_stage, responsible_stage.lower()
        ),
        "responsible_stage": responsible_stage,
        "round": iteration.iteration if iteration else 1,
        "adjustment_id": adjustment.adjustment_id if adjustment else "",
        "issue_fingerprint": iteration.issue_fingerprint if iteration else "",
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


def _read_ledger(state: Dict[str, Any]) -> list[Dict[str, Any]]:
    raw = state.get(_LEDGER_KEY)
    return [entry for entry in (raw if isinstance(raw, list) else []) if isinstance(entry, dict)]


async def validate_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Validate the immutable EXECUTE outputs and emit a typed gate + next_action."""
    from app.domain.validation.validate import validate_aggregate
    from app.domain.validation.validate_gate import evaluate_validate_gate
    from app.modules.schema.contracts.parse_contracts import SpatialPlanningIntent
    from app.modules.schema.contracts.planned_state_contracts import PlannedState
    from app.modules.schema.contracts.parcel_change_contracts import ParcelChangeSet
    from app.modules.schema.contracts.parse_result_contracts import IntentCompilationResult
    from app.modules.schema.contracts.selection_contracts import SiteSelectionDecision
    from app.modules.schema.contracts.execution_plan_contracts import ExecutionPlan, ExecutionResult

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
    executor = BoundedAdjustmentExecutor()
    result = await executor.apply(state, report)
    ledger = _read_ledger(state)
    patch: Dict[str, Any] = {}

    if result.status == "applied":
        candidates = await executor.plan(state, report)
        chosen = candidates[0] if candidates else None
        responsible_stage = str(chosen.responsible_stage if chosen else "EXECUTE") or "EXECUTE"
        route = _RETRY_ROUTE_BY_STAGE.get(responsible_stage, "HUMAN")
        gate = _override_gate_route(
            gate, route, reason=f"executor_applied:{responsible_stage}"
        )
        next_action = _next_action_recompute(responsible_stage, result, chosen)
        if result.iteration is not None:
            ledger = [*ledger, result.iteration.model_dump(mode="json")]
        patch = {_LEDGER_KEY: ledger}
    elif result.status == "noop":
        next_action = _next_action_forward("reconcile")
    else:
        failure = result.failure
        code = str(failure.code if failure else "unresolved")
        message = str(failure.message if failure else "validation unresolved")
        gate = _override_gate_route(gate, "HUMAN", reason=f"executor_{result.status}:{code}")
        next_action = _next_action_human(result.status, code, message)

    ref = persist_stage_artifact(state, "validate", "ValidationReport", report)
    return {
        **stage_completion_patch(
            state,
            "validate",
            output_refs={"validation_report": ref},
            gate=gate,
            context_patch=_adopt_context(state, context),
            retry_patch=retry_patch,
        ),
        "next_action": next_action,
        **patch,
    }


__all__ = ["validate_node"]
