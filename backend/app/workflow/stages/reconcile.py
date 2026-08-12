"""RECONCILE stage service."""

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


async def reconcile_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Reconcile intervention -> selection -> execution -> planned outputs."""
    from app.agent.reconcile.aggregate import reconcile_aggregate
    from app.agent.reconcile.gate import evaluate_reconcile_gate
    from app.modules.schema.contracts.l3_contracts import PlanningProgram
    from app.modules.schema.contracts.spatial_reference_contracts import SpatialReferenceSpec
    from app.modules.schema.contracts.grounding_contracts import GroundingResult
    from app.modules.schema.contracts.selection_contracts import SiteSelectionDecision
    from app.modules.schema.contracts.parcel_change_contracts import ParcelChangeSet
    from app.modules.schema.contracts.planned_state_contracts import PlannedState
    from app.modules.schema.contracts.parse_result_contracts import IntentCompilationResult
    from app.modules.schema.contracts.execution_plan_contracts import ExecutionPlan, ExecutionResult
    from app.modules.schema.contracts.reconciliation_contracts import ReconciliationInconsistency, ReconciliationReport

    retry_patch = _retry_patch(state, "reconcile")
    context = await _require_context(state)
    program = _load_ref_artifact(state, "planning_program", PlanningProgram)
    if program is None:
        report = ReconciliationReport(inconsistencies=[ReconciliationInconsistency(
            intervention_id="__missing_program__",
            field="planning_program",
            expected="non-null PlanningProgram",
            actual="None",
            severity="error",
            responsible_stage="L3",
        )])
    else:
        intent = _load_ref_artifact(state, "target_projection", IntentCompilationResult)
        specs = [_to_typed(item, SpatialReferenceSpec) for item in (getattr(intent, "spatial_reference_specs", None) or [])]
        execution_result = _load_ref_artifact(state, "execution_result", ExecutionResult)
        parcel_changeset = None
        planned_state = None
        if execution_result is not None:
            from app.workflow.stages.support import _load_embedded_artifact
            parcel_changeset = _load_embedded_artifact(state, execution_result.parcel_changeset_ref, ParcelChangeSet)
            planned_state = _load_embedded_artifact(state, execution_result.planned_state_ref, PlannedState)
        report = reconcile_aggregate(
            program,
            specs,
            _load_ref_artifact(state, "grounding_result", GroundingResult),
            _load_ref_artifact(state, "site_selection", SiteSelectionDecision),
            parcel_changeset,
            planned_state,
            intent,
            execution_plan=_load_ref_artifact(state, "execution_plan", ExecutionPlan),
            execution_result=execution_result,
            run_id=_run_id(state),
        )
    input_keys = {
        "planning_program", "target_projection", "grounding_result", "site_selection",
        "execution_plan", "execution_result",
        "validation_report", "deferral_ledger",
    }
    input_refs = {
        key: value for key, value in (state.get("artifact_refs") or {}).items() if key in input_keys
    }
    gate = _evaluate_progress_gate(
        evaluate_reconcile_gate,
        report,
        input_artifact_refs=input_refs,
        previous_gate=state.get("reconcile_gate"),
    )
    ref = persist_stage_artifact(state, "reconcile", "ReconciliationReport", report)
    return stage_completion_patch(
        state,
        "reconcile",
        output_refs={"reconciliation_report": ref},
        gate=gate,
        context_patch=_adopt_context(state, context),
        retry_patch=retry_patch,
    )


__all__ = ["reconcile_node"]
