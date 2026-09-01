"""VALIDATE subgraph — deterministic orchestration of the 9 checks into a typed ValidationReport.

Calls each Task 1 check function, flattens the resulting ValidationCheck list, then
builds a ValidationReport with overall_passed, issues grouped by responsibility stage,
and a Provenance record. No LLM, no KG, no MIP — deterministic only.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, List

from app.workflow.validation.validate_checks import (
    check_accessibility,
    check_area_conservation,
    check_candidate_materialization,
    check_bundle_snapshot_lineage,
    check_classification_missing,
    check_contract_completeness,
    check_continuity,
    check_hard_constraints,
    check_overlap,
    check_topology,
    check_traceability,
    check_worker_failures,
)
from app.contracts.artifacts.provenance import Provenance
from app.contracts.validation.validation_report_contracts import (
    ValidationCheck,
    ValidationIssue,
    ValidationReport,
)


def check_spatial_changeset(
    planned_state: Any,
    spatial_changeset: Any,
    execution_result: Any,
) -> list[ValidationCheck]:
    """Validate immutable generic geometry without repairing it."""

    spatial_results = [
        item
        for item in list(getattr(execution_result, "task_results", None) or [])
        if str(getattr(item, "status", "") or "") == "succeeded"
        and str(getattr(item, "expected_output_kind", "") or "") != "action"
    ]
    planned_features = list(getattr(planned_state, "features", None) or [])
    required = bool(spatial_results or planned_features)
    if spatial_changeset is None:
        return [ValidationCheck(
            check_id="spatial_changeset_presence",
            code="spatial_changeset_missing" if required else "spatial_changeset_not_applicable",
            check_name="generic SpatialChangeSet presence",
            passed=not required,
            actual_value="missing",
            expected_value=("non-empty SpatialChangeSet" if required else "not applicable"),
            responsible_stage="EXECUTE",
            affected_target_ids=sorted({
                str(getattr(item, "target_id", "") or "")
                for item in spatial_results
                if str(getattr(item, "target_id", "") or "")
            }),
            fix_suggestion="EXECUTE must persist the approval-bound SpatialChangeSet",
        )]
    try:
        from app.contracts.execute.spatial_change_contracts import SpatialChangeSet

        typed = SpatialChangeSet.model_validate(
            spatial_changeset.model_dump(mode="python")
            if hasattr(spatial_changeset, "model_dump")
            else spatial_changeset
        )
    except Exception as exc:
        return [ValidationCheck(
            check_id="spatial_changeset_contract",
            code="spatial_changeset_contract_invalid",
            check_name="generic spatial geometry and lineage contract",
            passed=False,
            actual_value=f"{type(exc).__name__}: {exc}",
            expected_value="valid, non-empty, digest-bound SpatialChangeSet",
            responsible_stage="EXECUTE",
            fix_suggestion=(
                "retry EXECUTE from the approved DATA resources; VALIDATE must not repair geometry"
            ),
        )]
    change_ids = {str(item.feature_id) for item in typed.features}
    planned_ids = {str(item.feature_id) for item in planned_features}
    task_ids = {
        str(feature_id)
        for result in spatial_results
        for feature_id in list(getattr(result, "feature_ids", None) or [])
        if str(feature_id).strip()
    }
    artifact_refs = {
        str(ref)
        for result in spatial_results
        for ref in list(getattr(result, "output_artifact_refs", None) or [])
        if str(ref).strip()
    }
    expected_artifact_refs = {
        f"spatial-feature:{feature_id}" for feature_id in task_ids
    }
    checks = [ValidationCheck(
        check_id="spatial_changeset_contract",
        code="spatial_changeset_contract_valid",
        check_name="generic spatial geometry and lineage contract",
        passed=True,
        actual_value=f"features={len(change_ids)}; operations={len(typed.operations)}",
        expected_value="one valid lineage-complete operation per feature",
        responsible_stage="EXECUTE",
        evidence_refs=sorted(typed.source_refs),
    )]
    planned_match = change_ids == planned_ids
    checks.append(ValidationCheck(
        check_id="spatial_planned_state_consistency",
        code=("spatial_planned_state_consistent" if planned_match else "spatial_planned_state_drift"),
        check_name="SpatialChangeSet to PlannedState consistency",
        passed=planned_match,
        actual_value=f"changes={sorted(change_ids)}; planned={sorted(planned_ids)}",
        expected_value="identical feature identity set",
        responsible_stage="EXECUTE",
        affected_target_ids=sorted({str(item.target_id) for item in typed.features}),
        fix_suggestion="rebuild PlannedState from the exact SpatialChangeSet",
    ))
    task_match = task_ids == change_ids and expected_artifact_refs.issubset(artifact_refs)
    checks.append(ValidationCheck(
        check_id="spatial_execution_result_consistency",
        code=("spatial_execution_result_consistent" if task_match else "spatial_execution_result_drift"),
        check_name="task result to SpatialChangeSet consistency",
        passed=task_match,
        actual_value=(
            f"tasks={sorted(task_ids)}; changes={sorted(change_ids)}; "
            f"artifact_refs={sorted(artifact_refs)}"
        ),
        expected_value="every change feature is claimed once by a real output artifact ref",
        responsible_stage="EXECUTE",
        fix_suggestion="abort and recommit the complete spatial execution batch",
    ))
    return checks


def check_spatial_output_views(
    spatial_changeset: Any,
    *,
    planned_entity_set: Any = None,
    planned_representation_set: Any = None,
    execution_trace: Any = None,
) -> list[ValidationCheck]:
    """Prove the three EXECUTE views are exact projections, not side outputs."""

    if spatial_changeset is None:
        return []
    if any(
        item is None
        for item in (
            planned_entity_set,
            planned_representation_set,
            execution_trace,
        )
    ):
        return [ValidationCheck(
            check_id="spatial_output_views",
            code="spatial_output_view_missing",
            check_name="planned entity/representation/trace views",
            passed=False,
            actual_value="one or more typed EXECUTE views are missing",
            expected_value="three CAS-reloadable views",
            responsible_stage="EXECUTE",
            fix_suggestion="reproject all typed views from the same SpatialChangeSet",
        )]
    try:
        from app.contracts.execute.spatial_change_contracts import (
            ExecutionTrace,
            PlannedEntitySet,
            PlannedRepresentationSet,
            SpatialChangeSet,
        )

        changes = SpatialChangeSet.model_validate(
            spatial_changeset.model_dump(mode="python")
        )
        entities = PlannedEntitySet.model_validate(
            planned_entity_set.model_dump(mode="python")
        )
        representations = PlannedRepresentationSet.model_validate(
            planned_representation_set.model_dump(mode="python")
        )
        trace = ExecutionTrace.model_validate(
            execution_trace.model_dump(mode="python")
        )
        feature_by_id = {item.feature_id: item for item in changes.features}
        representation_by_feature = {
            item.feature_id: item for item in representations.representations
        }
        entity_representation_refs = {
            ref
            for item in entities.entities
            for ref in item.representation_refs
        }
        planned_representation_refs = {
            item.planned_representation_ref
            for item in representations.representations
        }
        trace_change_refs = {item.change_ref for item in trace.operations}
        change_refs = {item.change_ref for item in changes.operations}
        consistent = (
            set(feature_by_id) == set(representation_by_feature)
            and entity_representation_refs == planned_representation_refs
            and set(trace.planned_representation_refs) == planned_representation_refs
            and trace_change_refs == change_refs
            and all(
                representation_by_feature[feature_id].geometry_wkt
                == feature.geometry_wkt
                and representation_by_feature[feature_id].geometry_digest
                == feature.geometry_digest
                for feature_id, feature in feature_by_id.items()
            )
        )
    except Exception as exc:
        consistent = False
        detail = f"{type(exc).__name__}: {exc}"
    else:
        detail = (
            f"entities={len(entities.entities)}; "
            f"representations={len(representations.representations)}; "
            f"trace_operations={len(trace.operations)}"
        )
    return [ValidationCheck(
        check_id="spatial_output_views",
        code=("spatial_output_views_consistent" if consistent else "spatial_output_views_drift"),
        check_name="planned entity/representation/trace views",
        passed=consistent,
        actual_value=detail,
        expected_value="exact identity, geometry and operation projection",
        responsible_stage="EXECUTE",
        fix_suggestion="abort and rebuild typed views from SpatialChangeSet",
    )]


def check_delivery_spatial_snapshot(
    spatial_changeset: Any,
    delivery_spatial_snapshot: Any,
    *,
    expected_parent_digests: dict[str, str] | None = None,
) -> list[ValidationCheck]:
    """Verify the immutable render input before DELIVER is allowed to read it."""

    change_features = {
        str(item.feature_id): item
        for item in list(getattr(spatial_changeset, "features", None) or [])
    }
    if delivery_spatial_snapshot is None:
        return [ValidationCheck(
            check_id="delivery_spatial_snapshot",
            code="delivery_spatial_snapshot_missing",
            check_name="EXECUTE-bound DeliverySpatialSnapshot",
            passed=False,
            actual_value="missing",
            expected_value="checksum-bound snapshot or explicit diagnostic-only snapshot",
            responsible_stage="EXECUTE",
            fix_suggestion="rebuild the snapshot before the EXECUTE atomic commit",
        )]
    try:
        from app.contracts.delivery.spatial_delivery_contracts import (
            DeliverySpatialSnapshot,
        )
        from app.infrastructure.export.delivery_snapshot import (
            load_complete_planned_geojson,
            load_snapshot_gis_data,
            load_snapshot_planned_overlays,
        )

        snapshot = DeliverySpatialSnapshot.model_validate(
            delivery_spatial_snapshot.model_dump(mode="python")
        )
        checksum_payload = snapshot.model_dump(mode="json")
        recorded_checksum = str(checksum_payload.get("checksum") or "")
        checksum_payload["checksum"] = ""
        actual_checksum = hashlib.sha256(
            json.dumps(
                checksum_payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        if not recorded_checksum or recorded_checksum != actual_checksum:
            raise ValueError("snapshot checksum mismatch")
        if snapshot.delivery_status == "diagnostic_only":
            if change_features:
                raise ValueError(
                    "diagnostic-only snapshot cannot carry committed spatial changes"
                )
            if (
                snapshot.current_layers
                or snapshot.planned_overlay_layers
                or snapshot.complete_planned_landuse is not None
            ):
                raise ValueError(
                    "diagnostic-only snapshot unexpectedly exposes spatial layers"
                )
            for key, expected in dict(expected_parent_digests or {}).items():
                if expected and snapshot.parent_digests.get(key) != expected:
                    raise ValueError("snapshot parent digest mismatch: " + key)
            detail = "diagnostic_only:no_normalized_spatial_data"
            passed = True
            return [ValidationCheck(
                check_id="delivery_spatial_snapshot",
                code="delivery_spatial_snapshot_diagnostic_only",
                check_name="EXECUTE-bound DeliverySpatialSnapshot",
                passed=True,
                actual_value=detail,
                expected_value=(
                    "checksum-bound snapshot or explicit diagnostic-only snapshot"
                ),
                responsible_stage="EXECUTE",
            )]
        baseline = load_snapshot_gis_data(snapshot)
        load_complete_planned_geojson(snapshot)
        overlays = load_snapshot_planned_overlays(snapshot)
        generic = overlays.get("planned_features_geojson") or {}
        overlay_features = {
            str((item.get("properties") or {}).get("feature_id") or ""): item
            for item in list(generic.get("features") or [])
        }
        if set(overlay_features) != set(change_features):
            raise ValueError("planned overlay feature identity differs from changeset")
        for feature_id, change in change_features.items():
            properties = overlay_features[feature_id].get("properties") or {}
            if (
                str(properties.get("geometry_digest") or "")
                != str(getattr(change, "geometry_digest", "") or "")
            ):
                raise ValueError(
                    "planned overlay geometry digest differs from changeset: "
                    + feature_id
                )
        if not baseline:
            raise ValueError("snapshot has no DATA baseline")
        for key, expected in dict(expected_parent_digests or {}).items():
            if expected and snapshot.parent_digests.get(key) != expected:
                raise ValueError("snapshot parent digest mismatch: " + key)
        detail = (
            f"baseline_layers={len(baseline)}; "
            f"planned_features={len(overlay_features)}"
        )
        passed = True
    except Exception as exc:
        detail = f"{type(exc).__name__}: {exc}"
        passed = False
    return [ValidationCheck(
        check_id="delivery_spatial_snapshot",
        code=(
            "delivery_spatial_snapshot_valid"
            if passed
            else "delivery_spatial_snapshot_invalid"
        ),
        check_name="EXECUTE-bound DeliverySpatialSnapshot",
        passed=passed,
        actual_value=detail,
        expected_value="checksum-bound baseline and exact SpatialChangeSet overlays",
        responsible_stage="EXECUTE",
        fix_suggestion=(
            "abort EXECUTE and rebuild the immutable snapshot from DATA and SpatialChangeSet"
        ),
    )]


def _check_id_to_stage(check: ValidationCheck) -> str:
    """Map a check to its issues_by_stage key (the responsible_stage Literal value as-is)."""
    return check.responsible_stage


def _check_to_issue(check: ValidationCheck) -> ValidationIssue:
    stage = _check_id_to_stage(check)
    message = f"{check.check_name}: {check.actual_value}" if check.actual_value else check.check_name
    return ValidationIssue(
        stage=stage,
        severity="error" if not check.passed else "warning",
        code=check.check_id,
        message=message,
        detail=check.fix_suggestion or None,
        check_id=check.check_id,
        actual_value=check.actual_value,
        expected_value=check.expected_value,
        affected_parcels=list(check.affected_parcels),
        affected_target_ids=list(check.affected_target_ids),
        evidence_refs=list(check.evidence_refs),
        fix_suggestion=check.fix_suggestion,
    )


def validate_aggregate(
    planned_state: Any,
    changeset: Any,
    intent: Any,
    constraint_index: Any,
    run_id: str = "",
    decision: Any = None,
    execution_plan: Any = None,
    execution_result: Any = None,
    bundle_snapshot_digest: str = "",
    spatial_changeset: Any = None,
    planned_entity_set: Any = None,
    planned_representation_set: Any = None,
    execution_trace: Any = None,
    delivery_spatial_snapshot: Any = None,
    delivery_snapshot_parent_digests: dict[str, str] | None = None,
) -> ValidationReport:
    """Validate typed execution outputs; render layers are not fact inputs."""
    if planned_state is None:
        typed_worker_checks = check_worker_failures(execution_result)
        if typed_worker_checks:
            issues_by_stage: dict[str, list[ValidationIssue]] = {}
            for check in typed_worker_checks:
                issue = _check_to_issue(check)
                issues_by_stage.setdefault(issue.stage, []).append(issue)
            return ValidationReport(
                checks=typed_worker_checks,
                overall_passed=False,
                issues_by_stage=issues_by_stage,
                adjustments=[],
                provenance=Provenance(
                    source="validate_aggregate",
                    run_id=run_id,
                    module="app.workflow.validation.validate",
                    natural_language_description=(
                        "planned_state blocked by target-bound worker failures"
                    ),
                ),
            )
        missing_check = ValidationCheck(
            check_id="missing_planned_state",
            check_name="planned_state presence",
            passed=False,
            actual_value="None",
            expected_value="non-null PlannedState",
            responsible_stage="EXECUTE",
            fix_suggestion="EXECUTE produced no planned_state; retry EXECUTE",
        )
        return ValidationReport(
            checks=[missing_check],
            overall_passed=False,
            issues_by_stage={"EXECUTE": [_check_to_issue(missing_check)]},
            adjustments=[],
            provenance=Provenance(
                source="validate_aggregate", run_id=run_id,
                module="app.workflow.validation.validate",
                natural_language_description="blocked: planned_state is None",
            ),
        )

    all_checks: List[ValidationCheck] = []
    all_checks.extend(check_hard_constraints(planned_state, constraint_index))
    all_checks.extend(check_area_conservation(changeset))
    all_checks.extend(check_topology(planned_state))
    all_checks.extend(check_candidate_materialization(planned_state))
    all_checks.extend(check_overlap(planned_state))
    all_checks.extend(check_continuity(planned_state))
    all_checks.extend(check_accessibility(planned_state, intent))
    all_checks.extend(check_contract_completeness(
        planned_state,
        changeset,
        intent,
        execution_plan=execution_plan,
    ))
    all_checks.extend(check_classification_missing(planned_state))
    all_checks.extend(check_traceability(
        execution_plan,
        execution_result,
    ))
    all_checks.extend(check_worker_failures(execution_result))
    all_checks.extend(check_bundle_snapshot_lineage(
        planned_state,
        execution_plan,
        execution_result,
        bundle_snapshot_digest,
    ))
    all_checks.extend(check_spatial_changeset(
        planned_state,
        spatial_changeset,
        execution_result,
    ))
    all_checks.extend(check_spatial_output_views(
        spatial_changeset,
        planned_entity_set=planned_entity_set,
        planned_representation_set=planned_representation_set,
        execution_trace=execution_trace,
    ))
    all_checks.extend(check_delivery_spatial_snapshot(
        spatial_changeset,
        delivery_spatial_snapshot,
        expected_parent_digests=delivery_snapshot_parent_digests,
    ))

    overall_passed = all(c.passed for c in all_checks)

    issues_by_stage: dict = {}
    for check in all_checks:
        if check.passed:
            continue
        issue = _check_to_issue(check)
        issues_by_stage.setdefault(issue.stage, []).append(issue)

    provenance = Provenance(
        source="validate_aggregate",
        run_id=run_id,
        module="app.workflow.validation.validate",
        natural_language_description=f"VALIDATE aggregate: {len(all_checks)} checks",
    )

    return ValidationReport(
        checks=all_checks,
        overall_passed=overall_passed,
        issues_by_stage=issues_by_stage,
        adjustments=[],
        provenance=provenance,
    )


__all__ = ["validate_aggregate"]
