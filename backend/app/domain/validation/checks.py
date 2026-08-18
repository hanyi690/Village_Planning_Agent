"""Deterministic chain-coverage reconciliation checks for the RECONCILE subgraph.

Six pure, deterministic checks that verify the planning chain
(L3 -> PARSE spec -> GROUND candidate -> SELECT -> EXECUTE change ->
planned state) is fully covered and attribute each finding to the
responsibility stage that should fix it:

  1. check_intervention_coverage      -> L3      intervention compiled to a spec
  2. check_spec_candidate_coverage    -> GROUND  spec produced a candidate site
  3. check_candidate_selection_coverage -> SELECT  candidate selected
  4. check_selection_change_coverage  -> EXECUTE selection produced a parcel change
  5. check_change_planned_coverage    -> EXECUTE change produced a planned parcel
  6. check_quantitative_drift         -> L3      text area range vs planned output

No LLM, no KG, no MIP — pure container/list math only.
"""

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


def _deferred_targets(decision) -> set[str]:
    if decision is None:
        return set()
    factors = getattr(decision, "decision_factors", None) or {}
    return {str(value) for value in (factors.get("deferred_targets") or [])}


def check_intervention_coverage(program, specs, decision=None) -> list[ReconciliationInconsistency]:
    interventions = list(getattr(program, "interventions", None) or [])
    specs = list(specs or [])
    inconsistencies: list[ReconciliationInconsistency] = []
    deferred = _deferred_targets(decision)
    for i, intervention in enumerate(interventions):
        intervention_id = str(getattr(intervention, "intervention_id", ""))
        if intervention_id in deferred:
            continue
        if i >= len(specs) or specs[i] is None:
            inconsistencies.append(
                _inc(
                    intervention_id,
                    "spec",
                    intervention.intervention_id,
                    "",
                    stage="L3",
                )
            )
    return inconsistencies


def check_spec_candidate_coverage(specs, grounding_result, decision=None) -> list[ReconciliationInconsistency]:
    specs = list(specs or [])
    candidates = list(getattr(grounding_result, "candidates", None) or [])
    inconsistencies: list[ReconciliationInconsistency] = []
    deferred = _deferred_targets(decision)
    for i in range(len(specs)):
        spec = specs[i]
        ref = str(
            getattr(spec, "intervention_id", None)
            or getattr(spec, "project_ref", None)
            or ""
        )
        if ref in deferred:
            continue
        if len(candidates) < i + 1:
            inconsistencies.append(
                _inc(
                    f"spec-{i}",
                    "candidate",
                    f"candidate-for-spec-{i}",
                    "",
                    stage="GROUND",
                )
            )
    return inconsistencies


def check_candidate_selection_coverage(grounding_result, decision) -> list[ReconciliationInconsistency]:
    selected = set(getattr(decision, "selected_combination", None) or [])
    candidates = list(getattr(grounding_result, "candidates", None) or [])
    candidate_bsms = {bsm for site in candidates for bsm in site.source_parcels}
    inconsistencies: list[ReconciliationInconsistency] = []
    deferred = _deferred_targets(decision)
    for site in candidates:
        ref = str(getattr(site, "target_ref", None) or getattr(site, "project_ref", None) or "")
        if ref in deferred:
            continue
        if not (set(site.source_parcels) & selected):
            inconsistencies.append(
                _inc(
                    site.site_id,
                    "selection",
                    site.site_id,
                    "",
                    stage="SELECT",
                )
            )
    return inconsistencies


def check_selection_change_coverage(decision, changeset) -> list[ReconciliationInconsistency]:
    change_bsms: set[str] = set()
    for change in getattr(changeset, "changes", None) or []:
        change_bsms.add(change.bsm)
        change_bsms.update(change.derived_from_bsms)
    selected = list(getattr(decision, "selected_combination", None) or [])
    inconsistencies: list[ReconciliationInconsistency] = []
    for bsm in selected:
        if bsm not in change_bsms:
            inconsistencies.append(
                _inc(
                    bsm,
                    "change",
                    bsm,
                    "",
                    stage="EXECUTE",
                )
            )
    return inconsistencies


def check_change_planned_coverage(changeset, planned_state) -> list[ReconciliationInconsistency]:
    planned_parcels = list(getattr(planned_state, "parcels", None) or [])
    planned_bsms = {p.bsm for p in planned_parcels}
    planned_derived = {b for p in planned_parcels for b in p.derived_from_bsms}
    inconsistencies: list[ReconciliationInconsistency] = []
    for change in getattr(changeset, "changes", None) or []:
        if change.bsm not in planned_bsms and not (set(change.derived_from_bsms) & planned_derived):
            inconsistencies.append(
                _inc(
                    change.bsm,
                    "planned",
                    change.bsm,
                    "",
                    stage="EXECUTE",
                )
            )
    return inconsistencies


def check_quantitative_drift(program, planned_state) -> list[ReconciliationInconsistency]:
    interventions = list(getattr(program, "interventions", None) or [])
    area_ranges = [iv.area_range_ha for iv in interventions if iv.area_range_ha is not None]
    if not area_ranges:
        return []
    planned_parcels = list(getattr(planned_state, "parcels", None) or [])
    positive_area_parcels = [
        float(getattr(parcel, "area_ha", 0.0) or 0.0)
        for parcel in planned_parcels
        if float(getattr(parcel, "area_ha", 0.0) or 0.0) > 0.0
    ]
    # Area ranges describe parcel/zone quantities.  A scenario that only
    # materializes source-backed overlay/facility features has no parcel-area
    # measurement to compare; treating zero-filled placeholder parcels as a
    # measured 0 ha manufactures an L3 failure and blocks delivery.
    if not positive_area_parcels:
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
    "check_intervention_coverage",
    "check_spec_candidate_coverage",
    "check_candidate_selection_coverage",
    "check_selection_change_coverage",
    "check_change_planned_coverage",
    "check_quantitative_drift",
]
