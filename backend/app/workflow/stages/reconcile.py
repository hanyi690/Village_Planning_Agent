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
    require_upstream_gates,
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
    require_upstream_gates(
        dict(state),
        (
            "data", "kg", "evidence", "l1", "l2", "l3",
            "target_projection", "ground", "select", "validate",
        ),
    )
    from app.workflow.validation.reconcile import reconcile_aggregate
    from app.workflow.validation.reconcile_gate import evaluate_reconcile_gate
    from app.contracts.l3.l3_contracts import PlanningProgram
    from app.contracts.ground.spatial_reference_contracts import SpatialReferenceSpec
    from app.contracts.ground.grounding_contracts import GroundingResult
    from app.contracts.ground.grounded_problem import GroundedPlanningProblem
    from app.contracts.execute.parcel_change_contracts import ParcelChangeSet
    from app.contracts.execute.planned_state_contracts import PlannedState
    from app.contracts.execute.spatial_change_contracts import SpatialChangeSet
    from app.contracts.target_projection.parse_result_contracts import IntentCompilationResult
    from app.contracts.execute.execution_plan_contracts import ExecutionPlan, ExecutionResult
    from app.contracts.validation.validation_certificate_contracts import ValidationCertificate
    from app.contracts.delivery.reconciliation_contracts import (
        FinalManifest,
        ReconciliationInconsistency,
    )

    retry_patch = _retry_patch(state, "reconcile")
    context = await _require_context(state)
    program = _load_ref_artifact(state, "planning_program", PlanningProgram)
    validation_certificate = None
    if program is None:
        report = FinalManifest(inconsistencies=[ReconciliationInconsistency(
            intervention_id="__missing_program__",
            field="planning_program",
            expected="non-null PlanningProgram",
            actual="None",
            severity="error",
            responsible_stage="L3",
        )])
    else:
        validation_certificate = _load_ref_artifact(
            state, "validation_certificate", ValidationCertificate
        )
        intent = _load_ref_artifact(state, "target_projection", IntentCompilationResult)
        specs = [_to_typed(item, SpatialReferenceSpec) for item in (getattr(intent, "spatial_reference_specs", None) or [])]
        execution_result = _load_ref_artifact(state, "execution_result", ExecutionResult)
        grounding_result = _load_ref_artifact(state, "grounding_result", GroundingResult)
        scoped_problem = _load_ref_artifact(
            state, "scoped_grounding_problem", GroundedPlanningProblem
        )
        if scoped_problem is not None and grounding_result is not None:
            grounding_result = grounding_result.model_copy(
                update={"problem": scoped_problem}
            )
        parcel_changeset = None
        spatial_changeset = None
        planned_state = None
        if execution_result is not None:
            from app.workflow.stages.support import _load_embedded_artifact
            parcel_changeset = _load_embedded_artifact(state, execution_result.parcel_changeset_ref, ParcelChangeSet)
            planned_state = _load_embedded_artifact(state, execution_result.planned_state_ref, PlannedState)
            spatial_changeset = _load_embedded_artifact(
                state,
                execution_result.spatial_changeset_ref,
                SpatialChangeSet,
            )
        report = reconcile_aggregate(
            program=program,
            specs=specs,
            grounding_result=grounding_result,
            changeset=parcel_changeset,
            planned_state=planned_state,
            intent=intent,
            execution_plan=_load_ref_artifact(state, "execution_plan", ExecutionPlan),
            execution_result=execution_result,
            spatial_changeset=spatial_changeset,
            run_id=_run_id(state),
        )
        if validation_certificate is None or not validation_certificate.can_reconcile:
            from app.workflow.validation.reconcile import (
                reconcile_gaps_from_inconsistencies,
            )

            inconsistencies = [
                    *list(report.inconsistencies or []),
                    ReconciliationInconsistency(
                        intervention_id="__validation_certificate__",
                        field="validation_certificate",
                        expected="passed certificate with committed atomic execution",
                        actual=(
                            "missing"
                            if validation_certificate is None
                            else str(validation_certificate.status)
                        ),
                        severity="error",
                        responsible_stage="VALIDATE",
                    ),
                ]
            report = report.model_copy(update={
                "inconsistencies": inconsistencies,
                "remaining_gaps": reconcile_gaps_from_inconsistencies(
                    inconsistencies
                ),
                "status": "human_required",
            })
    input_keys = {
        "planning_program", "target_projection", "grounding_result", "scenario_set", "planning_scenario", "approved_execution_input",
        "execution_plan", "execution_result",
        "validation_report", "validation_certificate", "deferral_ledger",
        "scoped_grounding_problem",
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
    ref = persist_stage_artifact(state, "reconcile", "FinalManifest", report)
    return stage_completion_patch(
        state,
        "reconcile",
        output_refs={"final_manifest": ref},
        gate=gate,
        context_patch=_adopt_context(state, context),
        retry_patch=retry_patch,
    )


__all__ = ["reconcile_node"]
