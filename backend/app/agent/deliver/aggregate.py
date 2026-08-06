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
    DeliveryManifest,
    HumanItem,
    TraceabilityEntry,
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


def _build_planned_view(current_parcels, planned_state) -> list:
    """Build the complete planned-parcel view for land-balance closure.

    ``PlannedState.parcels`` only carries changed parcels (the changeset);
    unchanged current parcels must be carried through as preserves so the
    planned total area can close against the current total within tolerance.
    ``current_parcels`` are the L1 current parcels; a current parcel is
    considered changed when its ``bsm`` appears in any planned parcel's
    ``derived_from_bsms`` or equals a planned parcel's ``bsm``.
    """
    planned_parcels = list(getattr(planned_state, "parcels", None) or [])
    if not current_parcels:
        return planned_parcels
    changed_bsms: set = set()
    for pp in planned_parcels:
        changed_bsms.add(str(getattr(pp, "bsm", "") or ""))
        for src in getattr(pp, "derived_from_bsms", None) or []:
            changed_bsms.add(str(src))
    view = list(planned_parcels)
    for cur in current_parcels:
        bsm = str(getattr(cur, "bsm", "") or "")
        if not bsm or bsm in changed_bsms:
            continue
        code = (
            getattr(cur, "planning_land_use", "")
            or getattr(cur, "dlbm", "")
            or "0000"
        )
        area_sqm = float(getattr(cur, "area_sqm", 0) or 0)
        area_ha = float(getattr(cur, "area_ha", 0) or 0)
        view.append(
            {
                "bsm": bsm,
                "planning_land_use": code,
                "zone_type": code,
                "area_ha": area_ha if area_ha > 0 else (area_sqm / 10000.0 if area_sqm else 0.0),
                "geometry": "",
                "derived_from_bsms": [],
                "decided_by": "preserve",
                "operation": "preserve",
                "area_change_ha": 0.0,
            }
        )
    return view


def deliver_aggregate(
    planned_state,
    validation_report,
    reconciliation_report,
    upstream_gates,
    export_result: dict | None,
    *,
    current_parcels=None,
    run_id: str = "",
) -> DeliveryManifest:
    """Run deliver checks and build a typed DeliveryManifest."""
    coverage_matrix = getattr(reconciliation_report, "coverage_matrix", None) or CoverageMatrix()
    traceability = build_traceability_from_coverage(coverage_matrix)
    deliverables = build_deliverables_from_export(export_result)

    check_items: list[HumanItem] = []
    check_items.extend(check_statutory_layers_complete(export_result))
    check_items.extend(check_traceability_complete(coverage_matrix))
    check_items.extend(check_classification_for_statutory(validation_report))

    upstream_items = collect_upstream_human_items(upstream_gates)

    gate = check_delivery_gate(
        current_parcels=list(current_parcels or []),
        planned_parcels=_build_planned_view(current_parcels, planned_state),
    )

    pending_human_items = check_items + upstream_items
    blocking = [item for item in pending_human_items if item.blocking]
    classification_complete = not any(
        item.item_id == "hi-class-0" for item in check_items
    )
    no_blocking_items = not blocking
    statutory_complete = gate.passed and no_blocking_items and classification_complete

    provenance = Provenance(
        source="deliver_aggregate",
        run_id=run_id,
        module="app.agent.deliver.aggregate",
        natural_language_description=f"DELIVER aggregate: {len(traceability)} interventions traced",
    )

    return DeliveryManifest(
        deliverables=deliverables,
        traceability=traceability,
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
