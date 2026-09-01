"""DELIVER stage entrypoint.

DELIVER is the only stage allowed to render and export delivery products.  It
reads the exact DeliverySpatialSnapshot frozen by EXECUTE plus validation and
reconciliation control artifacts; it never reopens DATA or rebuilds geometry.
"""

from __future__ import annotations

from typing import Any, Dict

from app.workflow.delivery.aggregate import deliver_aggregate
from app.workflow.delivery.delivery_renderer import render_delivery_artifacts
from app.workflow.delivery.delivery_exporter import export_delivery_products
from app.workflow.delivery.render_layers import build_delivery_render_layers
from app.workflow.delivery.gate import evaluate_deliver_gate, summarize_planning_output
from app.contracts.delivery.deferral_contracts import DeferralLedger
from app.contracts.execute.execution_plan_contracts import ExecutionResult
from app.contracts.execute.planned_state_contracts import PlannedState
from app.contracts.delivery.spatial_delivery_contracts import DeliverySpatialSnapshot
from app.contracts.delivery.reconciliation_contracts import FinalManifest
from app.contracts.validation.validation_report_contracts import ValidationReport
from app.contracts.validation.validation_certificate_contracts import ValidationCertificate
from app.workflow.stage_adapter import persist_stage_artifact
from app.workflow.stages.support import (
    _load_ref_artifact,
    _load_embedded_artifact,
    _retry_patch,
    _run_id,
    require_upstream_gates,
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
    generic_features = list(getattr(planned_state, "features", None) or [])
    planned_feature_count = len(generic_features) or sum(
        len(getattr(planned_state, field, None) or [])
        for field in (
            "parcels", "zones", "overlays", "facilities", "roads", "axes",
        )
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
    """Render and export only the immutable EXECUTE-bound spatial snapshot."""
    require_upstream_gates(
        dict(state),
        (
            "data", "kg", "evidence", "l1", "l2", "l3",
            "target_projection", "ground", "select", "validate", "reconcile",
        ),
    )

    retry_patch = _retry_patch(state, "deliver")
    execution_result = _load_ref_artifact(
        state,
        "execution_result",
        ExecutionResult,
    )
    if execution_result is None or execution_result.atomic_commit_status != "committed":
        raise RuntimeError("DELIVER requires a committed ExecutionResult")
    planned_state_descriptor = execution_result.planned_state_ref
    snapshot_descriptor = execution_result.delivery_spatial_snapshot_ref
    planned_state = _load_embedded_artifact(
        state,
        planned_state_descriptor.model_dump(mode="json")
        if planned_state_descriptor is not None
        else {},
        PlannedState,
    )
    delivery_snapshot = _load_embedded_artifact(
        state,
        snapshot_descriptor.model_dump(mode="json")
        if snapshot_descriptor is not None
        else {},
        DeliverySpatialSnapshot,
    )
    validation_report = _load_ref_artifact(state, "validation_report", ValidationReport)
    validation_certificate = _load_ref_artifact(
        state, "validation_certificate", ValidationCertificate
    )
    scenario_required = bool(
        (state.get("artifact_refs") or {}).get("planning_scenario")
    )
    reconciliation_report = _load_ref_artifact(state, "final_manifest", FinalManifest)
    deferral_ledger = _load_ref_artifact(state, "deferral_ledger", DeferralLedger)

    # DELIVER never repairs an upstream ledger. Missing deferral lineage is a
    # blocking diagnostic owned by RECONCILE/SELECT.
    ledger_ref = None

    validation_result = {}
    if validation_report is not None:
        validation_result = {"passed": validation_report.overall_passed}

    coverage_rows = list(
        getattr(
            getattr(reconciliation_report, "coverage_matrix", None),
            "rows",
            None,
        )
        or []
    )
    expected_spatial_output_count = sum(
        1
        for row in coverage_rows
        if str(getattr(row, "expected_output_kind", "") or "") != "action"
        and str(getattr(row, "status", "") or "") != "deferred"
    )
    if planned_state is None:
        raise RuntimeError("DELIVER requires persisted PlannedState")
    if validation_certificate is None or not validation_certificate.can_reconcile:
        raise RuntimeError(
            "DELIVER requires a passed ValidationCertificate bound to atomic execution"
        )
    if (
        snapshot_descriptor is None
        or validation_certificate.delivery_spatial_snapshot_ref
        != snapshot_descriptor.descriptor_digest
    ):
        raise RuntimeError(
            "DELIVER snapshot differs from the artifact validated by VALIDATE"
        )
    if reconciliation_report is None or not reconciliation_report.can_deliver:
        raise RuntimeError(
            "DELIVER is blocked by unresolved RECONCILE gaps"
        )
    if delivery_snapshot is None or snapshot_descriptor is None:
        raise RuntimeError(
            "DELIVER requires the EXECUTE-bound DeliverySpatialSnapshot"
        )
    delivery_snapshot_error = ""
    render_result = build_delivery_render_layers(delivery_snapshot)
    export_result = export_delivery_products(
        render_result,
        snapshot=delivery_snapshot,
        village_name=str((state.get("config") or {}).get("village_name") or ""),
        session_id=str(state.get("session_id") or ""),
        validation_result=validation_result,
    )
    export_result["planned_landuse_source"] = "delivery_spatial_snapshot"
    delivery_snapshot_ref = snapshot_descriptor

    current_parcels: list[Any] = []
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
        deferral_ledger=deferral_ledger,
        expected_spatial_output_count=expected_spatial_output_count,
        render_layer_count=len(render_result),
        render_error=render_error,
    )
    diagnostic_summary = dict(manifest.diagnostic_summary or {})
    if delivery_snapshot.delivery_status == "diagnostic_only":
        diagnostic_summary["spatial_context"] = {
            "status": "unavailable",
            "reason": str(
                (delivery_snapshot.provenance or {}).get("diagnostic_reason")
                or "execution snapshot contains no deliverable spatial output"
            ),
        }
    relation_rows: list[Any] = []
    hard_relation_failures = [
        str(code)
        for code in list(
            getattr(validation_certificate, "blocking_issue_codes", None) or []
        )
        if "relation" in str(code).casefold()
    ]
    final_relation_passed = bool(
        validation_certificate is not None
        and validation_certificate.can_reconcile
        and not hard_relation_failures
    )
    diagnostic_summary.update({
        "planning_output": planning_output,
        "spatial_yield": spatial_yield,
        "scenario": {
            "scenario_id": str(
                getattr(validation_certificate, "scenario_id", "") or ""
            ),
            "scenario_ref": str(
                getattr(validation_certificate, "baseline_ref", "") or ""
            ),
            "execution_trace_refs": list(
                getattr(planned_state, "execution_trace_refs", None) or []
            ),
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
