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
from app.domain.delivery.gate import evaluate_deliver_gate
from app.contracts.artifacts.deferral_contracts import DeferralLedger
from app.contracts.workflow.execution_plan_contracts import ExecutionPlan, ExecutionResult
from app.contracts.spatial.parcel_change_contracts import ParcelChangeSet
from app.contracts.spatial.planned_state_contracts import PlannedState
from app.contracts.artifacts.reconciliation_contracts import ReconciliationReport
from app.contracts.artifacts.validation_report_contracts import ValidationReport
from app.workflow.stage_adapter import persist_stage_artifact
from app.workflow.stages.support import (
    _adopt_context,
    _load_ref_artifact,
    _require_context,
    _retry_patch,
    _run_id,
    stage_completion_patch,
)


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
    reconciliation_report = _load_ref_artifact(state, "reconciliation_report", ReconciliationReport)
    execution_plan = _load_ref_artifact(state, "execution_plan", ExecutionPlan)
    deferral_ledger = _load_ref_artifact(state, "deferral_ledger", DeferralLedger)

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
    products = (
        build_spatial_delivery_products(
            session_id=str(state.get("session_id") or ""),
            village_name=str((state.get("config") or {}).get("village_name") or ""),
            workspace=workspace,
            planned_changes=list(getattr(changeset, "changes", None) or []),
            planned_state=planned_state,
            validation_result=validation_result,
        )
        if expected_spatial_output_count > 0
        else None
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
