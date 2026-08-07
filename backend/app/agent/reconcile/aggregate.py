"""Deterministic chain-coverage reconciliation orchestrator.

Aggregates the six RECONCILE checks into a ReconciliationReport and
traces each intervention through the planning chain (intervention ->
spec -> candidate -> selection -> change -> planned) into a typed
CoverageMatrix. Also absorbs the L3-targets -> PlannedState consistency
coverage as an additional check. No LLM, no KG, no MIP - deterministic only.
"""

from __future__ import annotations

from app.agent.reconcile.checks import (
    check_candidate_selection_coverage,
    check_change_planned_coverage,
    check_intervention_coverage,
    check_quantitative_drift,
    check_selection_change_coverage,
    check_spec_candidate_coverage,
)
from app.modules.schema.contracts.provenance import Provenance
from app.modules.schema.contracts.reconciliation_contracts import (
    CoverageMatrix,
    CoverageMatrixRow,
    ReconciliationInconsistency,
    ReconciliationReport,
)


def _inc(
    intervention_id: str,
    field: str,
    expected: str,
    actual: str,
    *,
    stage: str = "L3",
) -> ReconciliationInconsistency:
    return ReconciliationInconsistency(
        intervention_id=intervention_id,
        field=field,
        expected=expected,
        actual=actual,
        responsible_stage=stage,
    )


def _chain_status(spec_ok: bool, candidate_ok: bool, selection_ok: bool, change_ok: bool, planned_ok: bool) -> str:
    links = [spec_ok, candidate_ok, selection_ok, change_ok, planned_ok]
    if all(links):
        return "covered"
    if any(links):
        return "partial"
    return "missing"


def build_coverage_matrix(program, specs, grounding_result, decision, changeset, planned_state) -> CoverageMatrix:
    interventions = list(getattr(program, "interventions", None) or [])
    specs = list(specs or [])
    candidates = list(getattr(grounding_result, "candidates", None) or [])
    selected = list(getattr(decision, "selected_combination", None) or [])
    changes = list(getattr(changeset, "changes", None) or [])
    parcels = list(getattr(planned_state, "parcels", None) or [])
    rows: list[CoverageMatrixRow] = []
    for i, intervention in enumerate(interventions):
        # intervention -> spec: SpatialReferenceSpec carries no intervention_ref/
        # intervention_id, so there is no semantic key to join on; fall back to
        # positional pairing (PARSE emits specs in intervention order).
        spec_index = i if i < len(specs) else None
        # spec -> candidate: CandidateSite carries no spec_ref, so pairing is
        # positional (GROUND emits candidates in resolved-spec order).
        candidate = candidates[i] if i < len(candidates) else None
        # candidate -> selection: selected_combination holds bare BSM strings
        # with no site ref; link semantically by BSM membership in the candidate's
        # source parcels so this link is order-independent.
        candidate_bsms = set(getattr(candidate, "source_parcels", None) or []) if candidate else set()
        selected_bsm = next((b for b in selected if b in candidate_bsms), None)
        change_bsm = None
        if selected_bsm:
            for change in changes:
                if change.bsm == selected_bsm or selected_bsm in change.derived_from_bsms:
                    change_bsm = change.bsm
                    break
        planned_parcel_bsm = None
        if change_bsm:
            for parcel in parcels:
                if parcel.bsm == change_bsm or change_bsm in parcel.derived_from_bsms:
                    planned_parcel_bsm = parcel.bsm
                    break
        status = _chain_status(
            spec_index is not None,
            candidate is not None,
            selected_bsm is not None,
            change_bsm is not None,
            planned_parcel_bsm is not None,
        )
        rows.append(
            CoverageMatrixRow(
                intervention_id=intervention.intervention_id,
                spec_index=spec_index,
                candidate_site_id=candidate.site_id if candidate else "",
                selected_bsm=selected_bsm or "",
                change_bsm=change_bsm or "",
                planned_parcel_bsm=planned_parcel_bsm or "",
                status=status,
            )
        )
    return CoverageMatrix(rows=rows)


def check_l3_l4_target_coverage(intent, planned_state) -> list[ReconciliationInconsistency]:
    project_targets = [
        p for p in (getattr(intent, "project_targets", None) or [])
        if getattr(p, "requires_spatial", True)
    ]
    road_targets = list(getattr(intent, "road_targets", None) or [])
    zone_targets = list(getattr(intent, "zone_targets", None) or [])
    parcels = list(getattr(planned_state, "parcels", None) or [])
    roads = list(getattr(planned_state, "roads", None) or [])
    zones = list(getattr(planned_state, "zones", None) or [])
    inconsistencies: list[ReconciliationInconsistency] = []
    if project_targets and not parcels:
        inconsistencies.append(
            _inc(
                "",
                "l3_l4_project",
                f"{len(project_targets)} project target(s)",
                "0 planned parcels",
            )
        )
    if road_targets and len(roads) < len(road_targets):
        inconsistencies.append(
            _inc(
                "",
                "l3_l4_road",
                f"{len(road_targets)} road target(s)",
                str(len(roads)),
            )
        )
    for target in zone_targets:
        if target.area_ha is None:
            continue
        actual_ha = sum(z.area_ha for z in zones if z.derived_from_zone_target == target.land_use)
        if abs(actual_ha - float(target.area_ha)) > 1e-6:
            inconsistencies.append(
                _inc(
                    "",
                    "l3_l4_zone",
                    target.land_use or "",
                    str(actual_ha),
                )
            )
    return inconsistencies


def reconcile_aggregate(
    program=None,
    specs=None,
    grounding_result=None,
    decision=None,
    changeset=None,
    planned_state=None,
    intent=None,
    *,
    run_id: str = "",
) -> ReconciliationReport:
    all_inconsistencies: list[ReconciliationInconsistency] = []
    all_inconsistencies.extend(check_intervention_coverage(program, specs))
    all_inconsistencies.extend(check_spec_candidate_coverage(specs, grounding_result))
    all_inconsistencies.extend(check_candidate_selection_coverage(grounding_result, decision))
    all_inconsistencies.extend(check_selection_change_coverage(decision, changeset))
    all_inconsistencies.extend(check_change_planned_coverage(changeset, planned_state))
    all_inconsistencies.extend(check_quantitative_drift(program, planned_state))
    all_inconsistencies.extend(check_l3_l4_target_coverage(intent, planned_state))

    coverage_matrix = build_coverage_matrix(program, specs, grounding_result, decision, changeset, planned_state)

    provenance = Provenance(
        source="reconcile_aggregate",
        run_id=run_id,
        module="app.agent.reconcile.aggregate",
        natural_language_description=f"RECONCILE aggregate: {len(coverage_matrix.rows)} interventions traced",
    )

    return ReconciliationReport(
        coverage_matrix=coverage_matrix,
        inconsistencies=all_inconsistencies,
        provenance=provenance,
    )


__all__ = [
    "build_coverage_matrix",
    "check_l3_l4_target_coverage",
    "reconcile_aggregate",
]
