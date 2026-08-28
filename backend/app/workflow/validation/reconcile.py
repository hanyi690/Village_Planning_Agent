"""Deterministic chain-coverage reconciliation orchestrator.

Aggregates the six RECONCILE checks into a FinalManifest and
traces each intervention through the planning chain (intervention ->
spec -> candidate -> selection -> change -> planned) into a typed
CoverageMatrix. Also absorbs the L3-targets -> PlannedState consistency
coverage as an additional check. No LLM, no KG, no MIP - deterministic only.
"""

from __future__ import annotations

from app.workflow.validation.checks import check_quantitative_drift
from app.contracts.artifacts.provenance import Provenance
from app.contracts.delivery.reconciliation_contracts import (
    CoverageMatrix,
    CoverageMatrixRow,
    ReconciliationInconsistency,
    FinalManifest,
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


def build_coverage_matrix(
    *,
    execution_plan,
    execution_result,
) -> CoverageMatrix:
    """Build coverage from the canonical execution plan and result."""
    from app.core.common.execution_evidence import (
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
    from app.core.common.execution_evidence import (
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
    site_area_targets = [
        p for p in (getattr(intent, "site_area_targets", None) or [])
        if getattr(p, "requires_spatial", True)
        and str(getattr(p, "target_id", "")) not in deferred
    ]
    road_targets = list(getattr(intent, "road_targets", None) or [])
    zone_targets = list(getattr(intent, "zone_targets", None) or [])
    parcels = list(getattr(planned_state, "parcels", None) or [])
    roads = list(getattr(planned_state, "roads", None) or [])
    zones = list(getattr(planned_state, "zones", None) or [])
    inconsistencies: list[ReconciliationInconsistency] = []
    if site_area_targets and not parcels:
        inconsistencies.append(
            _inc(
                "",
                "l3_l4_project",
                f"{len(site_area_targets)} site-area target(s)",
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
) -> FinalManifest:
    all_inconsistencies: list[ReconciliationInconsistency] = []
    if execution_plan is None:
        all_inconsistencies.append(
            _inc(
                "__missing_execution_plan__",
                "execution_plan",
                "canonical ExecutionPlan",
                "None",
                stage="EXECUTE",
            )
        )
    else:
        all_inconsistencies.extend(
            check_target_execution_coverage(execution_plan, execution_result)
        )
        all_inconsistencies.extend(check_quantitative_drift(program, planned_state))
        all_inconsistencies.extend(check_l3_l4_target_coverage(intent, planned_state, decision))

    coverage_matrix = build_coverage_matrix(
        execution_plan=execution_plan,
        execution_result=execution_result,
    )

    provenance = Provenance(
        source="reconcile_aggregate",
        run_id=run_id,
        module="app.workflow.validation.reconcile",
        natural_language_description=f"RECONCILE aggregate: {len(coverage_matrix.rows)} targets traced",
    )

    return FinalManifest(
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
