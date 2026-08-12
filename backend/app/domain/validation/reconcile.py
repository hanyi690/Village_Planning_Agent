"""Deterministic chain-coverage reconciliation orchestrator.

Aggregates the six RECONCILE checks into a ReconciliationReport and
traces each intervention through the planning chain (intervention ->
spec -> candidate -> selection -> change -> planned) into a typed
CoverageMatrix. Also absorbs the L3-targets -> PlannedState consistency
coverage as an additional check. No LLM, no KG, no MIP - deterministic only.
"""

from __future__ import annotations

from app.domain.validation.checks import (
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


def _build_legacy_coverage_matrix(program, specs, grounding_result, decision, changeset, planned_state) -> CoverageMatrix:
    interventions = list(getattr(program, "interventions", None) or [])
    specs = list(specs or [])
    candidates = list(getattr(grounding_result, "candidates", None) or [])
    selected = list(getattr(decision, "selected_combination", None) or [])
    changes = list(getattr(changeset, "changes", None) or [])
    parcels = list(getattr(planned_state, "parcels", None) or [])
    deferred = {
        str(value)
        for value in ((getattr(decision, "decision_factors", None) or {}).get("deferred_targets") or [])
    }
    rows: list[CoverageMatrixRow] = []
    for intervention in interventions:
        int_id = str(getattr(intervention, "intervention_id", ""))
        target_id = str(getattr(intervention, "target_id", "") or int_id)
        # intervention -> spec: resolve ONLY via semantic keys (intervention_id
        # then target_id).  Positional pairing is intentionally removed: it
        # silently mis-associates when PARSE/GROUND ordering changes, which is
        # exactly the breakpoint this module exists to detect.
        spec_index = None
        for idx, spec in enumerate(specs):
            spec_int = str(getattr(spec, "intervention_id", "") or "")
            spec_tgt = str(getattr(spec, "target_id", "") or "")
            if spec_int and spec_int == int_id:
                spec_index = idx
                break
            if spec_tgt and spec_tgt == target_id:
                spec_index = idx
                break
        linked_spec = specs[spec_index] if spec_index is not None else None
        if str(int_id) in deferred:
            rows.append(
                CoverageMatrixRow(
                    intervention_id=intervention.intervention_id,
                    spec_index=spec_index,
                    status="deferred",
                )
            )
            continue
        # spec -> candidate: resolve ONLY via candidate.target_ref == spec.target_id.
        # Positional pairing is intentionally removed (see above).
        candidate = None
        if linked_spec is not None:
            spec_tgt = str(getattr(linked_spec, "target_id", "") or "")
            candidate = next(
                (c for c in candidates if str(getattr(c, "target_ref", "") or "") == spec_tgt),
                None,
            )
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


def build_coverage_matrix(
    program=None,
    specs=None,
    grounding_result=None,
    decision=None,
    changeset=None,
    planned_state=None,
    *,
    execution_plan=None,
    execution_result=None,
) -> CoverageMatrix:
    """Build v2 coverage from stable target IDs and declared output kinds."""
    if execution_plan is None:
        return _build_legacy_coverage_matrix(
            program, specs, grounding_result, decision, changeset, planned_state
        )

    from app.domain.common.execution_evidence import (
        active_output_covered,
        deferred_outcome_contradiction,
        group_execution_results,
        stable_output_key,
    )

    result_groups = group_execution_results(execution_result)
    rows: list[CoverageMatrixRow] = []
    for task in list(getattr(execution_plan, "worker_tasks", None) or []):
        task_id = str(getattr(task, "task_id", ""))
        target_id = str(getattr(task, "target_id", ""))
        output_kind = str(getattr(task, "expected_output_kind", "parcel"))
        results = result_groups.get(stable_output_key(task), [])
        artifacts = sorted({
            artifact
            for result in results
            for artifact in list(getattr(result, "output_artifacts", None) or [])
        })
        covered = active_output_covered(results, output_kind)
        rows.append(
            CoverageMatrixRow(
                target_id=target_id,
                target_type=str(getattr(task, "target_type", "")),
                expected_output_kind=output_kind,
                execution_task_id=task_id,
                output_artifacts=artifacts,
                intervention_id=target_id,
                status="covered" if covered else "failed",
            )
        )
    for task in list(getattr(execution_plan, "deferred_tasks", None) or []):
        target_id = str(getattr(task, "target_id", ""))
        results = result_groups.get(stable_output_key(task), [])
        contradiction = deferred_outcome_contradiction(results)
        rows.append(
            CoverageMatrixRow(
                target_id=target_id,
                target_type=str(getattr(task, "target_type", "")),
                expected_output_kind=str(getattr(task, "expected_output_kind", "parcel")),
                execution_task_id=str(getattr(task, "task_id", "")),
                intervention_id=target_id,
                output_artifacts=sorted({
                    artifact
                    for result in results
                    for artifact in list(getattr(result, "output_artifacts", None) or [])
                }),
                status="failed" if contradiction else "deferred",
            )
        )
    return CoverageMatrix(rows=rows)


def check_target_execution_coverage(
    execution_plan,
    execution_result,
) -> list[ReconciliationInconsistency]:
    from app.domain.common.execution_evidence import (
        active_output_covered,
        contradictory_statuses,
        deferred_outcome_contradiction,
        group_execution_results,
        stable_output_key,
    )

    result_groups = group_execution_results(execution_result)
    inconsistencies: list[ReconciliationInconsistency] = []
    planned_keys: set[tuple[str, str]] = set()
    for task in list(getattr(execution_plan, "worker_tasks", None) or []):
        key = stable_output_key(task)
        planned_keys.add(key)
        results = result_groups.get(key, [])
        statuses = sorted({str(getattr(result, "status", "")) for result in results})
        if contradictory_statuses(results):
            inconsistencies.append(
                _inc(
                    key[0],
                    "duplicate_execution_result",
                    f"one consistent outcome:{key[1]}",
                    f"statuses={statuses}",
                    stage="EXECUTE",
                )
            )
        elif not active_output_covered(results, key[1]):
            inconsistencies.append(
                _inc(
                    key[0],
                    "execution_status",
                    f"covered:{key[1]}",
                    f"statuses={statuses or ['missing']}",
                    stage="EXECUTE",
                )
            )
    for task in list(getattr(execution_plan, "deferred_tasks", None) or []):
        key = stable_output_key(task)
        planned_keys.add(key)
        results = result_groups.get(key, [])
        if deferred_outcome_contradiction(results):
            statuses = sorted({str(getattr(result, "status", "")) for result in results})
            inconsistencies.append(
                _inc(
                    key[0],
                    "deferred_outcome_contradiction",
                    f"deferred:{key[1]}",
                    f"statuses={statuses}",
                    stage="EXECUTE",
                )
            )
    for key in result_groups:
        if key not in planned_keys:
            inconsistencies.append(
                _inc(
                    key[0],
                    "execution_result",
                    "target and output kind declared by ExecutionPlan",
                    f"orphan:{key[1]}",
                    stage="EXECUTE",
                )
            )
    return inconsistencies


def check_l3_l4_target_coverage(intent, planned_state, decision=None) -> list[ReconciliationInconsistency]:
    deferred = {
        str(value)
        for value in ((getattr(decision, "decision_factors", None) or {}).get("deferred_targets") or [])
    }
    project_targets = [
        p for p in (getattr(intent, "project_targets", None) or [])
        if getattr(p, "requires_spatial", True)
        and str(getattr(p, "project_id", "")) not in deferred
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
    execution_plan=None,
    execution_result=None,
    run_id: str = "",
) -> ReconciliationReport:
    all_inconsistencies: list[ReconciliationInconsistency] = []
    if execution_plan is not None:
        all_inconsistencies.extend(
            check_target_execution_coverage(execution_plan, execution_result)
        )
        all_inconsistencies.extend(check_quantitative_drift(program, planned_state))
    else:
        all_inconsistencies.extend(check_intervention_coverage(program, specs, decision))
        all_inconsistencies.extend(check_spec_candidate_coverage(specs, grounding_result, decision))
        all_inconsistencies.extend(check_candidate_selection_coverage(grounding_result, decision))
        all_inconsistencies.extend(check_selection_change_coverage(decision, changeset))
        all_inconsistencies.extend(check_change_planned_coverage(changeset, planned_state))
        all_inconsistencies.extend(check_quantitative_drift(program, planned_state))
        all_inconsistencies.extend(check_l3_l4_target_coverage(intent, planned_state, decision))

    coverage_matrix = build_coverage_matrix(
        program,
        specs,
        grounding_result,
        decision,
        changeset,
        planned_state,
        execution_plan=execution_plan,
        execution_result=execution_result,
    )

    provenance = Provenance(
        source="reconcile_aggregate",
        run_id=run_id,
        module="app.domain.validation.reconcile",
        natural_language_description=f"RECONCILE aggregate: {len(coverage_matrix.rows)} targets traced",
    )

    return ReconciliationReport(
        coverage_matrix=coverage_matrix,
        inconsistencies=all_inconsistencies,
        provenance=provenance,
    )


__all__ = [
    "build_coverage_matrix",
    "check_target_execution_coverage",
    "check_l3_l4_target_coverage",
    "reconcile_aggregate",
]
