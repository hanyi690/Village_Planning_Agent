"""Pure atomic materialization boundary for EXECUTE worker batches."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Callable

from app.contracts.select.approval import ApprovedExecutionInput
from app.contracts.execute.parcel_change_contracts import ParcelChange
from app.contracts.execute.planned_state_contracts import PlannedState
from app.contracts.execute.spatial_change_contracts import (
    ExecutionTrace,
    PlannedEntitySet,
    PlannedRepresentationSet,
    SpatialChangeSet,
)
from app.contracts.delivery.spatial_delivery_contracts import DeliverySpatialSnapshot


@dataclass
class ExecutionBatch:
    """All worker output held in memory before a formal write."""

    approved_input: ApprovedExecutionInput | None = None
    expected_task_ids: list[str] = field(default_factory=list)
    worker_results: list[Any] = field(default_factory=list)
    parcel_changes: list[ParcelChange] = field(default_factory=list)
    planned_state: PlannedState | None = None
    spatial_changeset: SpatialChangeSet | None = None
    planned_entity_set: PlannedEntitySet | None = None
    planned_representation_set: PlannedRepresentationSet | None = None
    execution_trace: ExecutionTrace | None = None
    delivery_spatial_snapshot: DeliverySpatialSnapshot | None = None
    diagnostics: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class AtomicCommitResult:
    status: str
    commit_id: str = ""
    diagnostics: tuple[str, ...] = ()
    planned_state: PlannedState | None = None


def _worker_status(result: Any) -> str:
    return str(
        result.get("status", "") if isinstance(result, dict) else getattr(result, "status", "")
    )


def _feature_ids(result: Any) -> list[str]:
    values = result.get("feature_ids", []) if isinstance(result, dict) else getattr(result, "feature_ids", [])
    return [str(value) for value in values if str(value).strip()]


def _task_id(result: Any) -> str:
    value = result.get("task_id", "") if isinstance(result, dict) else getattr(result, "task_id", "")
    return str(value or "").strip()


def _output_kind(result: Any) -> str:
    value = (
        result.get("expected_output_kind", "")
        if isinstance(result, dict)
        else getattr(result, "expected_output_kind", "")
    )
    return str(value or "").strip()


def _geometry_kind_for_output(result: Any) -> str:
    value = _output_kind(result)
    return "polygon" if value == "parcel" else value


def _artifact_refs(result: Any) -> list[str]:
    values = (
        result.get("output_artifact_refs", [])
        if isinstance(result, dict)
        else getattr(result, "output_artifact_refs", [])
    )
    return [str(value) for value in values if str(value).strip()]


def commit_execution_batch(
    batch: ExecutionBatch,
    *,
    persist: Callable[[PlannedState], Any] | None = None,
) -> AtomicCommitResult:
    """Validate every worker result, then invoke the writer exactly once.

    A failed validation never calls ``persist`` and therefore cannot expose a
    partial PlannedState.  The writer callback is intentionally injected so
    this boundary can be tested without a live KG or artifact repository.
    """

    diagnostics = [str(item) for item in batch.diagnostics if str(item).strip()]
    if batch.approved_input is None:
        diagnostics.append("approved execution input is missing")
    elif not batch.approved_input.can_execute:
        diagnostics.append("approved execution input is not executable")
    if batch.planned_state is None:
        diagnostics.append("planned state is missing")
    non_successful = [
        item for item in batch.worker_results if _worker_status(item) != "succeeded"
    ]
    if non_successful:
        diagnostics.append("one or more worker results did not succeed")
    expected_values = [str(task_id).strip() for task_id in batch.expected_task_ids]
    expected_task_ids = {task_id for task_id in expected_values if task_id}
    if not expected_values or len(expected_task_ids) != len(expected_values):
        diagnostics.append("expected task ids must be non-empty and unique")
    if any(not task_id for task_id in expected_values):
        diagnostics.append("expected task ids must not be blank")
    actual_values = [_task_id(item) for item in batch.worker_results]
    actual_task_ids = {task_id for task_id in actual_values if task_id}
    if any(not task_id for task_id in actual_values):
        diagnostics.append("worker result task_id is missing")
    duplicate_task_ids = sorted(
        task_id
        for task_id in actual_task_ids
        if actual_values.count(task_id) > 1
    )
    if duplicate_task_ids:
        diagnostics.append("duplicate worker task results: " + ", ".join(duplicate_task_ids))
    if expected_task_ids:
        unexpected_task_ids = sorted(actual_task_ids - expected_task_ids)
        if unexpected_task_ids:
            diagnostics.append(
                "unexpected worker task results: " + ", ".join(unexpected_task_ids)
            )
        missing_task_ids = sorted(expected_task_ids - actual_task_ids)
        if missing_task_ids:
            diagnostics.append(
                "required worker task results are missing: " + ", ".join(missing_task_ids)
            )
        non_successful_expected = sorted(
            task_id
            for task_id, result in zip(actual_values, batch.worker_results)
            if task_id in expected_task_ids and _worker_status(result) != "succeeded"
        )
        if non_successful_expected:
            diagnostics.append(
                "required worker tasks are not succeeded: "
                + ", ".join(non_successful_expected)
            )
    feature_ids = [feature_id for item in batch.worker_results for feature_id in _feature_ids(item)]
    if len(feature_ids) != len(set(feature_ids)):
        diagnostics.append("duplicate materialized feature ids")
    spatial_results = [
        item
        for item in batch.worker_results
        if _worker_status(item) == "succeeded" and _output_kind(item) != "action"
    ]
    if spatial_results and batch.spatial_changeset is None:
        diagnostics.append("spatial change set is missing for spatial worker results")
    if spatial_results:
        required_views = {
            "planned entity set": batch.planned_entity_set,
            "planned representation set": batch.planned_representation_set,
            "execution trace": batch.execution_trace,
        }
        diagnostics.extend(
            f"{name} is missing for spatial worker results"
            for name, value in required_views.items()
            if value is None
        )
    if batch.delivery_spatial_snapshot is None:
        diagnostics.append("delivery spatial snapshot is missing from atomic execution")
    if batch.delivery_spatial_snapshot is not None:
        try:
            snapshot = DeliverySpatialSnapshot.model_validate(
                batch.delivery_spatial_snapshot.model_dump(mode="python")
            )
        except Exception:
            diagnostics.append("delivery spatial snapshot contract validation failed")
        else:
            if spatial_results and not snapshot.planned_overlay_layers:
                diagnostics.append("delivery spatial snapshot has no planned overlays")
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
                diagnostics.append("delivery spatial snapshot checksum mismatch")
            if spatial_results:
                try:
                    from app.infrastructure.export.delivery_snapshot import (
                        load_complete_planned_geojson,
                        load_snapshot_gis_data,
                        load_snapshot_planned_overlays,
                    )

                    load_snapshot_gis_data(snapshot)
                    load_complete_planned_geojson(snapshot)
                    load_snapshot_planned_overlays(snapshot)
                except Exception:
                    diagnostics.append("delivery spatial snapshot layer reload failed")
                if str((snapshot.quality_report or {}).get("status") or "") != "passed":
                    diagnostics.append("delivery spatial snapshot quality gate failed")
    if batch.spatial_changeset is not None:
        try:
            spatial_changeset = SpatialChangeSet.model_validate(
                batch.spatial_changeset.model_dump(mode="python")
            )
        except Exception:
            diagnostics.append("spatial change set contract validation failed")
            spatial_changeset = None
        if spatial_changeset is not None:
            change_features = {
                str(item.feature_id): item for item in spatial_changeset.features
            }
            change_feature_ids = set(change_features)
            referenced_feature_ids: set[str] = set()
            for result in spatial_results:
                result_feature_ids = set(_feature_ids(result))
                if not result_feature_ids:
                    diagnostics.append(
                        f"spatial task result has no feature refs: {_task_id(result)}"
                    )
                    continue
                missing = sorted(result_feature_ids - change_feature_ids)
                if missing:
                    diagnostics.append(
                        "spatial task references features outside change set: "
                        + ", ".join(missing)
                    )
                kind_mismatch = sorted(
                    feature_id
                    for feature_id in result_feature_ids & change_feature_ids
                    if str(change_features[feature_id].geometry_kind)
                    != _geometry_kind_for_output(result)
                )
                if kind_mismatch:
                    diagnostics.append(
                        "spatial task output kind differs from change feature: "
                        + ", ".join(kind_mismatch)
                    )
                expected_refs = {
                    f"spatial-feature:{feature_id}" for feature_id in result_feature_ids
                }
                if not expected_refs.issubset(set(_artifact_refs(result))):
                    diagnostics.append(
                        f"spatial task result has incomplete artifact refs: {_task_id(result)}"
                    )
                duplicate_refs = referenced_feature_ids & result_feature_ids
                if duplicate_refs:
                    diagnostics.append(
                        "spatial features are owned by multiple task results: "
                        + ", ".join(sorted(duplicate_refs))
                    )
                referenced_feature_ids.update(result_feature_ids)
            unclaimed = sorted(change_feature_ids - referenced_feature_ids)
            if unclaimed:
                diagnostics.append(
                    "spatial change set contains unclaimed features: "
                    + ", ".join(unclaimed)
                )
            planned_features = {
                str(item.feature_id): item
                for item in list(getattr(batch.planned_state, "features", None) or [])
            }
            if set(planned_features) != change_feature_ids or any(
                planned_features[feature_id].geometry_wkt
                != change_features[feature_id].geometry_wkt
                or planned_features[feature_id].geometry_digest
                != change_features[feature_id].geometry_digest
                for feature_id in change_feature_ids & set(planned_features)
            ):
                diagnostics.append("planned state geometry differs from spatial change set")
            if all(
                value is not None
                for value in (
                    batch.planned_entity_set,
                    batch.planned_representation_set,
                    batch.execution_trace,
                )
            ):
                try:
                    from app.infrastructure.artifacts.fingerprint import semantic_checksum
                    from app.modules.execute.spatial_output_projection import (
                        project_spatial_outputs,
                    )

                    expected_views = project_spatial_outputs(spatial_changeset)
                    actual_views = (
                        batch.planned_entity_set,
                        batch.planned_representation_set,
                        batch.execution_trace,
                    )
                    if any(
                        semantic_checksum(actual) != semantic_checksum(expected)
                        for actual, expected in zip(actual_views, expected_views)
                    ):
                        diagnostics.append(
                            "planned entity, representation or trace view differs from spatial change set"
                        )
                except Exception:
                    diagnostics.append("typed spatial output view validation failed")
    if diagnostics:
        return AtomicCommitResult(
            status="aborted",
            diagnostics=tuple(sorted(set(diagnostics))),
            planned_state=None,
        )
    if persist is not None:
        persist(batch.planned_state)
    raw = "|".join(
        [
            str(getattr(batch.approved_input, "fingerprint", "") or ""),
            str(getattr(batch.planned_state, "artifact_id", "") or ""),
            str(getattr(batch.spatial_changeset, "artifact_id", "") or ""),
            str(getattr(batch.delivery_spatial_snapshot, "checksum", "") or ""),
            str(len(batch.worker_results)),
        ]
    ).encode("utf-8")
    return AtomicCommitResult(
        status="committed",
        commit_id=f"commit:{hashlib.sha256(raw).hexdigest()[:20]}",
        diagnostics=(),
        planned_state=batch.planned_state,
    )


__all__ = ["ExecutionBatch", "AtomicCommitResult", "commit_execution_batch"]
