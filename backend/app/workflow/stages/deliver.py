"""DELIVER stage entrypoint.

DELIVER is the only stage allowed to assemble delivery products.  It reads
typed execution artifacts and the data-layer workspace, then persists the
single DeliverySpatialSnapshot used by render, export, and the manifest.
"""

from __future__ import annotations

from typing import Any, Dict

from app.domain.delivery.aggregate import deliver_aggregate
from app.domain.delivery.delivery_renderer import render_delivery_artifacts
from app.domain.delivery.delivery_snapshot_builder import build_spatial_delivery_products
from app.domain.delivery.gate import evaluate_deliver_gate, summarize_planning_output
from app.contracts.artifacts.deferral_contracts import DeferralLedger
from app.contracts.workflow.execution_plan_contracts import ExecutionPlan, ExecutionResult
from app.contracts.spatial.parcel_change_contracts import ParcelChangeSet
from app.contracts.spatial.planned_state_contracts import PlannedState
from app.contracts.artifacts.reconciliation_contracts import ReconciliationReport
from app.contracts.artifacts.validation_report_contracts import ValidationReport
from app.contracts.artifacts.validation_certificate_contracts import ValidationCertificate
from app.workflow.stage_adapter import persist_stage_artifact
from app.workflow.stages.support import (
    _adopt_context,
    _load_ref_artifact,
    _require_context,
    _retry_patch,
    _run_id,
    stage_completion_patch,
)


def _artifact_digest(state: Dict[str, Any], key: str) -> str:
    ref = (state.get("artifact_refs") or {}).get(key)
    if not isinstance(ref, dict):
        return ""
    return str(ref.get("digest") or ref.get("descriptor_digest") or "")


def _spatial_yield(
    state: Dict[str, Any],
    *,
    program: Any = None,
    projection: Any = None,
    grounding: Any = None,
    approved_input: Any = None,
    execution_plan: Any = None,
    execution_result: Any = None,
    planned_state: Any = None,
    render_layers: list[dict[str, Any]] | None = None,
    planning_output: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Record the spatial yield at every immutable stage boundary.

    Counts are diagnostics only; the stage artifacts remain authoritative.
    In particular, the delivery count is computed from the exact render input
    after baseline layers have been excluded by ``summarize_planning_output``.
    """
    graph = getattr(projection, "intent_graph", None)
    graph_nodes = (
        graph.get("nodes", []) if isinstance(graph, dict)
        else getattr(graph, "nodes", None) or []
    )
    target_count = len(getattr(program, "interventions", None) or [])
    if graph is not None:
        target_count = len(graph_nodes) or target_count
    candidate_count = len(getattr(grounding, "candidates", None) or [])
    selected_count = len(getattr(approved_input, "target_ids", None) or [])
    active_tasks = len(getattr(execution_plan, "worker_tasks", None) or [])
    deferred_tasks = len(getattr(execution_plan, "deferred_tasks", None) or [])
    task_results = list(getattr(execution_result, "task_results", None) or [])
    succeeded_tasks = sum(
        str(getattr(result, "status", "")) == "succeeded" for result in task_results
    )
    planned_feature_count = sum(
        len(getattr(planned_state, field, None) or [])
        for field in ("parcels", "zones", "overlays", "facilities", "roads", "axes")
    )
    render_output = planning_output or summarize_planning_output(render_layers or [])
    return [
        {
            "stage": "PlanningProgram",
            "input_count": 1 if program is not None else 0,
            "output_count": target_count,
            "deferred_count": len(getattr(program, "evidence_gaps", None) or []) if program is not None else 0,
            "non_baseline_feature_count": 0,
            "artifact_digest": _artifact_digest(state, "planning_program"),
        },
        {
            "stage": "TargetProjection",
            "input_count": target_count,
            "output_count": len(graph_nodes) if graph is not None else 0,
            "deferred_count": len(getattr(projection, "diagnostics", None) or []) if projection is not None else 0,
            "non_baseline_feature_count": 0,
            "artifact_digest": _artifact_digest(state, "target_projection"),
        },
        {
            "stage": "Grounding",
            "input_count": target_count,
            "output_count": candidate_count,
            "deferred_count": len(getattr(grounding, "unresolved", None) or []) if grounding is not None else 0,
            "non_baseline_feature_count": 0,
            "artifact_digest": _artifact_digest(state, "grounding_result"),
        },
        {
            "stage": "Selection",
            "input_count": candidate_count,
            "output_count": selected_count,
            "deferred_count": sum(
                str(getattr(item, "status", "")) == "deferred"
                for item in (getattr(approved_input, "target_ids", None) or [])
            ),
            "non_baseline_feature_count": 0,
            "artifact_digest": _artifact_digest(state, "approved_execution_input"),
        },
        {
            "stage": "Execution",
            "input_count": active_tasks + deferred_tasks,
            "output_count": succeeded_tasks,
            "deferred_count": deferred_tasks,
            "non_baseline_feature_count": 0,
            "artifact_digest": _artifact_digest(state, "execution_result"),
        },
        {
            "stage": "PlannedState",
            "input_count": succeeded_tasks,
            "output_count": planned_feature_count,
            "deferred_count": deferred_tasks,
            "non_baseline_feature_count": planned_feature_count,
            "artifact_digest": _artifact_digest(state, "planned_state"),
        },
        {
            "stage": "DeliverySnapshot",
            "input_count": planned_feature_count,
            "output_count": sum(render_output.get("layer_feature_counts", {}).values()),
            "deferred_count": 0,
            "non_baseline_feature_count": int(render_output.get("non_baseline_feature_count") or 0),
            "artifact_digest": _artifact_digest(state, "delivery_spatial_snapshot"),
        },
        {
            "stage": "RenderLayers",
            "input_count": len(render_layers or []),
            "output_count": sum(render_output.get("layer_feature_counts", {}).values()),
            "deferred_count": 0,
            "non_baseline_feature_count": int(render_output.get("non_baseline_feature_count") or 0),
            "artifact_digest": _artifact_digest(state, "render_layers"),
        },
    ]


async def deliver_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Build, validate, render, export, and persist delivery products."""

    retry_patch = _retry_patch(state, "deliver")
    context = await _require_context(state)
    workspace = getattr(context, "workspace", None)
    execution_result = _load_ref_artifact(state, "execution_result", ExecutionResult)
    planned_state = None
    changeset = None
    if execution_result is not None:
        from app.workflow.stages.support import _load_embedded_artifact
        planned_state = _load_embedded_artifact(state, execution_result.planned_state_ref, PlannedState)
        changeset = _load_embedded_artifact(state, execution_result.parcel_changeset_ref, ParcelChangeSet)
    validation_report = _load_ref_artifact(state, "validation_report", ValidationReport)
    validation_certificate = _load_ref_artifact(
        state, "validation_certificate", ValidationCertificate
    )
    from app.domain.validation.relation_validation import FinalScenarioValidation

    final_relation_validation = _load_ref_artifact(
        state,
        "final_relation_validation",
        FinalScenarioValidation,
    )
    scenario_required = bool(
        (state.get("artifact_refs") or {}).get("planning_scenario")
    )
    reconciliation_report = _load_ref_artifact(state, "reconciliation_report", ReconciliationReport)
    execution_plan = _load_ref_artifact(state, "execution_plan", ExecutionPlan)
    deferral_ledger = _load_ref_artifact(state, "deferral_ledger", DeferralLedger)
    from app.contracts.domain.l3_contracts import PlanningProgram
    from app.contracts.planning.approval import ApprovedExecutionInput
    from app.contracts.spatial.grounding_contracts import GroundingResult
    from app.contracts.workflow.parse_result_contracts import IntentCompilationResult

    program = _load_ref_artifact(state, "planning_program", PlanningProgram)
    projection = _load_ref_artifact(state, "target_projection", IntentCompilationResult)
    grounding = _load_ref_artifact(state, "grounding_result", GroundingResult)
    approved_input = _load_ref_artifact(
        state, "approved_execution_input", ApprovedExecutionInput
    )

    ledger_ref = None
    if execution_plan is not None:
        from app.contracts.artifacts.deferral_contracts import HumanDeferralDecision, TargetDeferral

        ledger_entries = list(getattr(deferral_ledger, "entries", None) or [])
        ledger_ids = {str(entry.target_id) for entry in ledger_entries}
        missing_deferred = [
            task
            for task in (getattr(execution_plan, "deferred_tasks", None) or [])
            if str(getattr(task, "target_id", ""))
            and str(getattr(task, "target_id", "")) not in ledger_ids
        ]
        if missing_deferred:
            decision = HumanDeferralDecision(
                decision_id=str(state.get("human_review_event_id") or "delivery-ledger-reconciliation"),
                decided_by="system:delivery-ledger-reconciliation",
                rationale=(
                    "ExecutionPlan already classified this target as deferred; "
                    "delivery recorded the missing immutable ledger link before export."
                ),
            )
            ledger_entries.extend(
                TargetDeferral(
                    target_id=str(task.target_id),
                    reason="execution_plan_deferred_ledger_reconciliation",
                    source_refs=(
                        "artifact:execution_plan:"
                        f"{(state.get('artifact_refs') or {}).get('execution_plan', {}).get('descriptor_digest', 'execution_plan')}",
                    ),
                    decision=decision,
                )
                for task in missing_deferred
            )
            deferral_ledger = DeferralLedger(entries=tuple(ledger_entries))
            ledger_ref = persist_stage_artifact(state, "deliver", "DeferralLedger", deferral_ledger)

    validation_result = {}
    if validation_report is not None:
        validation_result = {"passed": validation_report.overall_passed}

    expected_spatial_output_count = sum(
        1
        for task in (getattr(execution_plan, "worker_tasks", None) or [])
        if str(getattr(task, "expected_output_kind", "")) != "action"
    )
    # DELIVER owns the authoritative spatial snapshot even for a partial
    # execution.  When SELECT deferred every spatial target, the snapshot is
    # still needed to render the real current GIS state and to make the
    # deferred/planned distinction auditable.  Skipping this build based on
    # worker-task count used to create a valid CAS ref whose JSON payload was
    # null, contradicting the required DeliverySpatialSnapshot contract.
    products = build_spatial_delivery_products(
        session_id=str(state.get("session_id") or ""),
        village_name=str((state.get("config") or {}).get("village_name") or ""),
        workspace=workspace,
        planned_changes=list(getattr(changeset, "changes", None) or []),
        planned_state=planned_state,
        validation_result=validation_result,
    )
    if products.snapshot is None:
        raise RuntimeError(
            "DELIVER could not build DeliverySpatialSnapshot: "
            f"{products.error or 'unknown spatial snapshot error'}"
        )
    delivery_snapshot = products.snapshot if products else None
    delivery_snapshot_error = products.error if products else ""
    render_result = products.render_layers if products else []
    export_result = products.export_result if products else None
    delivery_snapshot_ref = persist_stage_artifact(
        state, "deliver", "DeliverySpatialSnapshot", delivery_snapshot
    )

    current_parcels = list(workspace.current_parcels()) if workspace is not None else []
    render_ref = persist_stage_artifact(state, "deliver", "RenderLayers", render_result)
    render_artifacts = render_delivery_artifacts(
        render_result,
        session_id=str(state.get("session_id") or ""),
        village_name=str((state.get("config") or {}).get("village_name") or ""),
        snapshot=delivery_snapshot,
        snapshot_error=delivery_snapshot_error,
    )
    render_error = ""
    if isinstance(render_artifacts.get("error"), dict):
        render_error = str(render_artifacts["error"].get("message") or "")
    quality = render_artifacts.get("quality") or {}
    if quality.get("status") != "passed":
        render_error = (
            "delivery render quality failed: "
            f"empty={quality.get('empty_geometry_count', 0)}, "
            f"invalid={quality.get('invalid_geometry_count', 0)}, "
            f"placeholder={quality.get('placeholder_geometry_count', 0)}"
        )
    planning_output = summarize_planning_output(render_result, delivery_snapshot)
    spatial_yield = _spatial_yield(
        state,
        program=program,
        projection=projection,
        grounding=grounding,
        approved_input=approved_input,
        execution_plan=execution_plan,
        execution_result=execution_result,
        planned_state=planned_state,
        render_layers=render_result,
        planning_output=planning_output,
    )
    manifest = deliver_aggregate(
        planned_state,
        validation_report,
        reconciliation_report,
        list(state.get("upstream_gates") or []),
        export_result,
        current_parcels=current_parcels,
        run_id=_run_id(state),
        execution_plan=execution_plan,
        execution_result=execution_result,
        deferral_ledger=deferral_ledger,
        expected_spatial_output_count=expected_spatial_output_count,
        render_layer_count=len(render_result),
        render_error=render_error,
    )
    diagnostic_summary = dict(manifest.diagnostic_summary or {})
    if products.spatial_context_unavailable:
        diagnostic_summary["spatial_context"] = {
            "status": "unavailable",
            "reason": products.spatial_context_reason,
        }
    relation_source = final_relation_validation or validation_report
    relation_rows = (
        list(getattr(relation_source, "satisfactions", None) or [])
        if relation_source is not None
        else []
    )
    final_relation_passed = (
        bool(getattr(final_relation_validation, "passed", False))
        if final_relation_validation is not None
        else not scenario_required
    )
    hard_relation_failures = [
        str(getattr(item, "relation_id", "") or "")
        for item in relation_rows
        if str(getattr(item, "criticality", "") or "") == "hard"
        and str(getattr(item, "status", "") or "") != "satisfied"
    ]
    if scenario_required and final_relation_validation is None:
        hard_relation_failures.append("final_relation_validation_missing")
    diagnostic_summary.update({
        "planning_output": planning_output,
        "spatial_yield": spatial_yield,
        "scenario": {
            "scenario_id": str(getattr(execution_result, "scenario_id", "") or ""),
            "scenario_ref": str(getattr(execution_result, "scenario_ref", "") or ""),
            "execution_trace_refs": list(
                getattr(execution_result, "execution_trace_refs", None) or []
            ) if execution_result is not None else [],
            "relation_validation_count": len(relation_rows),
            "hard_relation_failures": sorted(item for item in hard_relation_failures if item),
            "final_relation_validation_passed": final_relation_passed,
        },
        "validation_certificate": {
            "certificate_id": str(getattr(validation_certificate, "certificate_id", "") or ""),
            "status": str(getattr(validation_certificate, "status", "") or ""),
            "can_reconcile": bool(
                validation_certificate is not None
                and validation_certificate.can_reconcile
            ),
        },
    })
    certificate_blocked = scenario_required and (
        validation_certificate is None
        or not validation_certificate.can_reconcile
    )
    if certificate_blocked:
        # The manifest may still carry a diagnostic map, but DELIVER must not
        # advertise even partial scenario output as accepted without the
        # immutable VALIDATE certificate.
        diagnostic_summary["validation_certificate_gate"] = "blocked"
    if certificate_blocked:
        manifest = manifest.model_copy(update={
            "delivery_status": "partial",
            "statutory_complete": False,
            "diagnostic_summary": diagnostic_summary,
        })
    if (
        planning_output["status"] == "no_planning_output"
        or hard_relation_failures
        or not final_relation_passed
    ):
        # The current/complete-planned baseline layers are still useful for a
        # diagnostic map, but must never be advertised as a complete plan.
        manifest = manifest.model_copy(update={
            "delivery_status": "partial",
            "statutory_complete": False,
            "diagnostic_summary": diagnostic_summary,
        })
    else:
        manifest = manifest.model_copy(update={"diagnostic_summary": diagnostic_summary})
    gate = evaluate_deliver_gate(
        manifest,
        input_artifact_refs=state.get("artifact_refs") or {},
        previous_gate=state.get("deliver_gate"),
    )
    manifest_ref = persist_stage_artifact(state, "deliver", "DeliveryManifest", manifest)
    export_ref = persist_stage_artifact(state, "deliver", "ExportResult", export_result or {})
    render_artifacts_ref = persist_stage_artifact(
        state, "deliver", "RenderArtifacts", render_artifacts
    )
    completion = stage_completion_patch(
        state,
        "deliver",
        output_refs={
            "delivery_manifest": manifest_ref,
            "render_layers": render_ref,
            "delivery_spatial_snapshot": delivery_snapshot_ref,
            "deferral_ledger": ledger_ref,
            "export_result": export_ref,
            "render_artifacts": render_artifacts_ref,
        },
        gate=gate,
        context_patch=_adopt_context(state, context),
        retry_patch=retry_patch,
    )
    return {
        **completion,
        "delivery_status": manifest.delivery_status,
        "render_quality": render_artifacts.get("quality", {}),
        "planning_output": planning_output,
        "spatial_yield": spatial_yield,
        "deferral_summary": manifest.deferral_summary,
        "diagnostic_terminal": (
            {
                "stage": "deliver",
                "reason": "remaining_non_deferred_delivery_blockers",
                **manifest.diagnostic_summary,
            }
            if manifest.delivery_status == "diagnostic_only"
            else {}
        ),
    }


__all__ = ["deliver_node"]
