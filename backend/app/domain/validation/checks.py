"""Deterministic quantitative checks used by the canonical RECONCILE stage."""

from __future__ import annotations

from app.contracts.artifacts.reconciliation_contracts import ReconciliationInconsistency


def _inc(
    intervention_id: str,
    field: str,
    expected: str,
    actual: str,
    *,
    stage: str = "EXECUTE",
    severity: str = "error",
) -> ReconciliationInconsistency:
    return ReconciliationInconsistency(
        intervention_id=intervention_id,
        field=field,
        expected=expected,
        actual=actual,
        severity=severity,
        responsible_stage=stage,
    )


def check_quantitative_drift(program, planned_state) -> list[ReconciliationInconsistency]:
    interventions = list(getattr(program, "interventions", None) or [])
    planned_parcels = list(getattr(planned_state, "parcels", None) or [])
    # ``PlannedState.parcels`` contains both materialized target footprints
    # and preserved source remainders.  The latter are required for area
    # conservation, but they are not additional delivered planning quantity.
    # Counting them here turns a valid split (target footprints + one shared
    # remainder) into a false L3 quantitative drift.  Only active parcel
    # operations contribute to the target quantity check.
    positive_area_parcels = []
    active_intervention_refs: set[str] = set()
    for parcel in planned_parcels:
        if str(getattr(parcel, "operation", "") or "").lower() == "preserve":
            continue
        area_ha = float(getattr(parcel, "area_ha", 0.0) or 0.0)
        if area_ha > 0.0:
            positive_area_parcels.append(area_ha)
            for field in ("target_id", "project_ref", "intervention_id"):
                value = str(getattr(parcel, field, "") or "").strip()
                if value:
                    active_intervention_refs.add(value)
    # Area ranges describe parcel/zone quantities.  A scenario that only
    # materializes source-backed overlay/facility features has no parcel-area
    # measurement to compare; treating zero-filled placeholder parcels as a
    # measured 0 ha manufactures an L3 failure and blocks delivery.
    if not positive_area_parcels:
        return []

    # A program may contain many area-bearing interventions, while SELECT may
    # approve only a scoped subset (for example, a deferred 35 ha zone next to
    # two approved 100/120 m² footprints).  Reconcile against the approved
    # materialized targets, not every area claim in the source program.
    area_ranges = []
    for intervention in interventions:
        area_range = getattr(intervention, "area_range_ha", None)
        if area_range is None:
            continue
        if active_intervention_refs:
            refs = {
                str(getattr(intervention, field, "") or "").strip()
                for field in ("intervention_id", "target_id", "project_package_ref")
            }
            refs.discard("")
            if not refs.intersection(active_intervention_refs):
                continue
        area_ranges.append(area_range)
    if not area_ranges:
        return []

    total_planned_ha = sum(positive_area_parcels)
    expected_min = sum(r[0] for r in area_ranges)
    expected_max = sum(r[1] for r in area_ranges)
    if total_planned_ha < expected_min * 0.95 or total_planned_ha > expected_max * 1.05:
        return [
            _inc(
                "",
                "area",
                f"{expected_min}-{expected_max}",
                str(total_planned_ha),
                stage="L3",
            )
        ]
    return []


__all__ = [
    "check_quantitative_drift",
]
