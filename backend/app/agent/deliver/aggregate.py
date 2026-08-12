"""DELIVER aggregate — deterministic delivery manifest orchestrator.

Builds a typed DeliveryManifest from the upstream artifacts: traceability
populated from the RECONCILE CoverageMatrix, deliverables mapped from the
export package, pending human items collected from the deliver checks and
the upstream gates, and a delivery gate computed via
spatial_ops.land_balance.check_delivery_gate. statutory_complete blocks
"完整法定成果" (complete statutory output) when planning classification is
missing (08_DELIVERABLES_COMPLIANCE.md §3). No LLM, no KG — deterministic only.
"""

from __future__ import annotations

from app.agent.deliver.checks import (
    check_classification_for_statutory,
    check_statutory_layers_complete,
    check_traceability_complete,
)
from app.modules.schema.contracts.delivery_manifest_contracts import (
    Deliverable,
    DeliveryGate,
    DeliveryManifest,
    HumanItem,
    TraceabilityEntry,
)
from app.modules.schema.contracts.deferral_contracts import DeferralLedger
from app.modules.schema.contracts.execution_plan_contracts import (
    ExecutionPlan,
    ExecutionResult,
)
from app.modules.schema.contracts.provenance import Provenance
from app.modules.schema.contracts.reconciliation_contracts import CoverageMatrix
from app.modules.spatial_ops.land_balance import check_delivery_gate


def build_traceability_from_coverage(
    coverage_matrix: CoverageMatrix,
) -> list[TraceabilityEntry]:
    """Map each CoverageMatrixRow to a TraceabilityEntry (Wave K -> Wave L bridge)."""
    rows = list(getattr(coverage_matrix, "rows", None) or [])
    entries: list[TraceabilityEntry] = []
    for row in rows:
        entries.append(
            TraceabilityEntry(
                target_id=row.target_id,
                target_type=row.target_type,
                expected_output_kind=row.expected_output_kind,
                execution_task_id=row.execution_task_id,
                output_artifacts=list(row.output_artifacts),
                status=row.status,
                intervention_id=row.intervention_id,
                requirement_id="" if row.spec_index is None else str(row.spec_index),
                candidate_id=row.candidate_site_id,
                selection_id=row.selected_bsm,
                change_id=row.change_bsm,
                planned_ref=row.planned_parcel_bsm,
                deliverable_id="",
            )
        )
    return entries


def build_deliverables_from_export(export_result: dict | None) -> list[Deliverable]:
    """Map the export package's exported_files list to Deliverable entries."""
    if export_result is None:
        return []
    exported = list(export_result.get("exported_files", []) or [])
    deliverables: list[Deliverable] = []
    for i, path in enumerate(exported):
        deliverables.append(
            Deliverable(
                deliverable_id=f"deliverable-{i}",
                type="gdb_layer",
                path=str(path),
                format="geojson",
                description="",
            )
        )
    return deliverables


def collect_upstream_human_items(upstream_gates) -> list[HumanItem]:
    """Convert HUMAN-route PendingRequests from upstream gates to HumanItems."""
    gates = list(upstream_gates or [])
    items: list[HumanItem] = []
    for i, gate in enumerate(gates):
        route = getattr(gate, "feedback_route", None) or ""
        if route not in ("HUMAN", "human_review"):
            continue
        for pr in getattr(gate, "pending_requests", None) or []:
            reason = (getattr(pr, "context", None) or {}).get("reason", "") or route
            items.append(
                HumanItem(
                    item_id=f"hi-upstream-{i}",
                    description=getattr(pr, "request_type", "") or "上游未决问题",
                    reason=str(reason),
                    blocking=True,
                )
            )
    return items


def _planned_view_from_export(export_result: dict | None) -> list | None:
    """Read the same complete planned snapshot used by export and render."""
    if not isinstance(export_result, dict):
        return None
    geojson = export_result.get("planned_landuse_geojson")
    if not isinstance(geojson, dict):
        return None
    rows = []
    for feature in geojson.get("features", []) or []:
        properties = feature.get("properties") or {}
        area_ha = float(properties.get("area_ha") or 0)
        if area_ha <= 0:
            area_sqm = float(
                properties.get("area_sqm")
                or properties.get("DLMJ")
                or properties.get("area")
                or 0
            )
            area_ha = area_sqm / 10000.0
        rows.append({
            "bsm": properties.get("BSM") or properties.get("bsm") or "",
            "planning_land_use": (
                properties.get("planning_land_use")
                or properties.get("GHYTBM")
                or properties.get("QMDLBM")
                or properties.get("DLBM")
                or "0000"
            ),
            "zone_type": properties.get("zone_type") or properties.get("planning_zone") or "",
            "area_ha": area_ha,
            "geometry": "",
            "derived_from_bsms": list(properties.get("derived_from_bsms") or []),
        })
    return rows


def _deferral_summary(ledger: DeferralLedger | None) -> dict:
    entries = list(getattr(ledger, "entries", None) or [])
    return {
        "count": len(entries),
        "target_ids": [entry.target_id for entry in entries],
        "actions": [entry.decision.action for entry in entries],
    }


def _expected_spatial_outputs(plan: ExecutionPlan | None) -> int:
    return sum(
        1
        for task in (getattr(plan, "worker_tasks", None) or [])
        if str(getattr(task, "expected_output_kind", "")) != "action"
    )


def _execution_blockers(
    plan: ExecutionPlan | None,
    outcome: ExecutionResult | None,
    coverage_matrix: CoverageMatrix,
    ledger: DeferralLedger | None,
) -> list[HumanItem]:
    if plan is None:
        return []
    rows = {
        (str(row.target_id), str(row.expected_output_kind)): row
        for row in coverage_matrix.rows
    }
    results = {
        (str(result.target_id), str(result.expected_output_kind)): result
        for result in (getattr(outcome, "task_results", None) or [])
    }
    action_ids = {
        str(result.target_id)
        for result in (getattr(outcome, "action_results", None) or [])
    }
    blockers: list[HumanItem] = []
    for task in plan.worker_tasks:
        key = (str(task.target_id), str(task.expected_output_kind))
        row = rows.get(key)
        result = results.get(key)
        covered = row is not None and row.status == "covered"
        succeeded = result is not None and result.status == "succeeded"
        action_present = key[1] != "action" or key[0] in action_ids
        if covered and succeeded and action_present:
            continue
        blockers.append(HumanItem(
            item_id=f"hi-execution-{key[0]}",
            description=f"活动目标未形成可交付结果: {key[0]}",
            reason=(
                f"coverage={getattr(row, 'status', 'missing')}; "
                f"execution={getattr(result, 'status', 'missing')}; "
                f"output_kind={key[1]}"
            ),
            blocking=True,
        ))

    ledger_ids = {
        str(entry.target_id) for entry in (getattr(ledger, "entries", None) or [])
    }
    for task in plan.deferred_tasks:
        if str(task.target_id) in ledger_ids:
            continue
        blockers.append(HumanItem(
            item_id=f"hi-deferral-ledger-{task.target_id}",
            description=f"延期目标缺少法定台账记录: {task.target_id}",
            reason="ExecutionPlan.deferred_tasks must be backed by DeferralLedger.",
            blocking=True,
        ))
    return blockers


def deliver_aggregate(
    planned_state,
    validation_report,
    reconciliation_report,
    upstream_gates,
    export_result: dict | None,
    *,
    current_parcels=None,
    run_id: str = "",
    execution_plan: ExecutionPlan | None = None,
    execution_result: ExecutionResult | None = None,
    deferral_ledger: DeferralLedger | None = None,
    expected_spatial_output_count: int | None = None,
    render_layer_count: int = 0,
    render_error: str = "",
) -> DeliveryManifest:
    """Run deliver checks and build a typed DeliveryManifest."""
    coverage_matrix = getattr(reconciliation_report, "coverage_matrix", None) or CoverageMatrix()
    traceability = build_traceability_from_coverage(coverage_matrix)
    deliverables = build_deliverables_from_export(export_result)

    check_items: list[HumanItem] = []
    spatial_output_count = (
        _expected_spatial_outputs(execution_plan)
        if expected_spatial_output_count is None
        else max(0, int(expected_spatial_output_count))
    )
    check_items.extend(check_statutory_layers_complete(
        export_result,
        required=spatial_output_count > 0,
    ))
    check_items.extend(check_traceability_complete(coverage_matrix))
    check_items.extend(check_classification_for_statutory(validation_report))
    check_items.extend(_execution_blockers(
        execution_plan,
        execution_result,
        coverage_matrix,
        deferral_ledger,
    ))
    if spatial_output_count > 0 and render_layer_count <= 0:
        check_items.append(HumanItem(
            item_id="hi-render-empty",
            description="活动空间目标缺少可渲染几何",
            reason="DeliverySpatialSnapshot did not produce any render layer.",
            blocking=True,
        ))
    if spatial_output_count > 0 and render_error:
        check_items.append(HumanItem(
            item_id="hi-render-file",
            description="空间成果渲染文件生成失败",
            reason=render_error,
            blocking=True,
        ))

    upstream_items = collect_upstream_human_items(upstream_gates)

    land_balance_expected = any(
        str(getattr(task, "expected_output_kind", "")) in {"parcel", "polygon"}
        for task in (getattr(execution_plan, "worker_tasks", None) or [])
    )
    planned_geojson = (
        export_result.get("planned_landuse_geojson")
        if isinstance(export_result, dict)
        else None
    )
    planned_features = (
        (planned_geojson or {}).get("features", [])
        if isinstance(planned_geojson, dict)
        else []
    )
    has_material_planned_change = any(
        (feature.get("properties") or {}).get("change_status")
        not in {None, "preserved", "unchanged"}
        for feature in planned_features
        if isinstance(feature, dict)
    )
    if not has_material_planned_change:
        check_items.append(HumanItem(
            item_id="hi-no-parcel-changes",
            description="期末地类没有实际 ParcelChange",
            reason=(
                "complete_planned_landuse 仅保留现状地块；项目/设施定位点不能替代地块规划变更。"
            ),
            blocking=False,
        ))
    exported_planned = _planned_view_from_export(export_result)
    planned_for_balance = exported_planned or []
    gate = (
        check_delivery_gate(
            current_parcels=list(current_parcels or []),
            planned_parcels=planned_for_balance,
        )
        if land_balance_expected or execution_plan is None
        else DeliveryGate(land_balance_closed=True, zones_complete=True)
    )
    if spatial_output_count > 0 and not gate.passed:
        check_items.append(HumanItem(
            item_id="hi-delivery-gate",
            description="空间成果未通过交付硬门槛",
            reason="; ".join(gate.failures),
            blocking=True,
        ))

    pending_human_items = check_items + upstream_items
    blocking = [item for item in pending_human_items if item.blocking]
    classification_complete = not any(
        item.item_id == "hi-class-0" for item in check_items
    )
    no_blocking_items = not blocking
    deferral_summary = _deferral_summary(deferral_ledger)
    delivery_status = (
        "diagnostic_only"
        if blocking
        else "partial"
        if deferral_summary["count"] > 0 or not has_material_planned_change
        else "complete"
    )
    statutory_complete = (
        spatial_output_count > 0
        and delivery_status == "complete"
        and gate.passed
        and no_blocking_items
        and classification_complete
    )
    diagnostic_summary = {
        "blocking_count": len(blocking),
        "blocking_item_ids": [item.item_id for item in blocking],
        "reasons": [item.reason for item in blocking],
    } if blocking else {}

    provenance = Provenance(
        source="deliver_aggregate",
        run_id=run_id,
        module="app.agent.deliver.aggregate",
        natural_language_description=f"DELIVER aggregate: {len(traceability)} interventions traced",
    )

    return DeliveryManifest(
        delivery_status=delivery_status,
        deliverables=deliverables,
        traceability=traceability,
        action_results=list(getattr(execution_result, "action_results", None) or []),
        deferral_ledger=deferral_ledger,
        deferral_summary=deferral_summary,
        diagnostic_summary=diagnostic_summary,
        expected_spatial_output_count=spatial_output_count,
        render_layer_count=render_layer_count,
        pending_human_items=pending_human_items,
        delivery_gate=gate,
        provenance=provenance,
        statutory_complete=statutory_complete,
        statutory_complete_breakdown={
            "delivery_gate": gate.passed,
            "no_blocking_items": no_blocking_items,
            "classification_complete": classification_complete,
        },
    )


__all__ = [
    "build_traceability_from_coverage",
    "build_deliverables_from_export",
    "collect_upstream_human_items",
    "deliver_aggregate",
]
