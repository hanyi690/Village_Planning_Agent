"""VALIDATE stage service."""

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


def _to_typed(data: Any, cls: type) -> Any:
    if data is None or isinstance(data, cls):
        return data
    if isinstance(data, dict):
        try:
            return cls(**data)
        except Exception:
            return data
    return data


async def validate_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Validate the immutable EXECUTE outputs and emit a gate."""
    from app.agent.validate.aggregate import validate_aggregate
    from app.agent.validate.gate import evaluate_validate_gate
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
    ref = persist_stage_artifact(state, "validate", "ValidationReport", report)
    return stage_completion_patch(
        state,
        "validate",
        output_refs={"validation_report": ref},
        gate=gate,
        context_patch=_adopt_context(state, context),
        retry_patch=retry_patch,
    )


__all__ = ["validate_node"]
