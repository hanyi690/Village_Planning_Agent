"""Axis materializer: development-axis layer from approved intent."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from app.modules.execute.execute_state import ExecuteAgentState
from app.modules.execute.workers.worker_common import _attach_feature_lineage, _execution_intent_from_plan, _intent_list, _plan_tasks, _scenario_features_for_layer, _task_enabled, _task_execution_result, _task_value
from app.contracts.execute.execution_plan_contracts import WorkerResult
from app.infrastructure.logging import get_logger

logger = get_logger(__name__)


def _value(item: Any, name: str, default: Any = None) -> Any:
    if isinstance(item, Mapping):
        return item.get(name, default)
    return getattr(item, name, default)


def _source_feature_id(feature: Any) -> str:
    raw = _value(feature, "_raw", {}) or {}
    if isinstance(raw, Mapping):
        value = raw.get("source_feature_id")
        if value:
            return str(value).strip()
    properties = _value(feature, "properties", {}) or {}
    if isinstance(properties, Mapping):
        return str(properties.get("source_feature_id") or "").strip()
    return ""


def _line_geometry(feature: Any) -> dict[str, Any] | None:
    geometry = _value(feature, "geometry")
    if not isinstance(geometry, Mapping):
        return None
    if str(geometry.get("type") or "") not in {"LineString", "MultiLineString"}:
        return None
    try:
        from shapely.geometry import shape

        parsed = shape(geometry)
        if parsed.is_empty or not parsed.is_valid or parsed.geom_type not in {
            "LineString", "MultiLineString",
        }:
            return None
    except Exception:
        return None
    return deepcopy(dict(geometry))


def _workspace_line_index(workspace: Any) -> dict[str, Any]:
    """Index authoritative line features by their ingested source ID.

    This deliberately ignores parcel geometry, centroids, endpoints, and
    labels.  A line can enter the execution layer only through a source ID
    that is present on the current workspace line feature.
    """
    groups = _value(workspace, "lines", {}) or {}
    index: dict[str, Any] = {}
    if not isinstance(groups, Mapping):
        return index
    for features in groups.values():
        for feature in features or []:
            source_id = _source_feature_id(feature)
            if source_id and _line_geometry(feature) is not None:
                index.setdefault(source_id, feature)
    return index


def materialize_authoritative_axis_lines(axis: Any, workspace: Any) -> tuple[list[dict[str, Any]], str]:
    """Materialize only explicitly requested source-backed line features.

    Returns ``([], reason)`` for an absent/foreign ID.  The old AxisBuilder
    path generated a point or a corridor from parcel centroids; that output is
    useful only as a candidate visualization and must never be an execution
    geometry.
    """
    raw_ids = _value(axis, "source_feature_ids", []) or []
    source_ids = list(dict.fromkeys(str(item).strip() for item in raw_ids if str(item).strip()))
    if not source_ids:
        return [], "axis_source_feature_ids_missing"
    index = _workspace_line_index(workspace)
    missing = [source_id for source_id in source_ids if source_id not in index]
    if missing:
        return [], f"axis_source_feature_geometry_missing:{','.join(missing)}"
    target_id = str(_value(axis, "target_id", "") or "").strip()
    features: list[dict[str, Any]] = []
    for position, source_id in enumerate(source_ids, start=1):
        source = index[source_id]
        geometry = _line_geometry(source)
        if geometry is None:
            return [], f"axis_source_feature_geometry_invalid:{source_id}"
        properties = {
            "target_id": target_id,
            "source_feature_id": source_id,
            "source_feature_ids": source_ids,
            "axis_type": str(_value(axis, "axis_type", "primary") or "primary"),
            "name": str(_value(axis, "label", "") or "") or "发展轴",
            "materialization_method": "authoritative_source_line",
        }
        features.append({
            "type": "Feature",
            "id": f"AXIS-{target_id}-{position:04d}",
            "geometry": geometry,
            "properties": properties,
        })
    return features, ""


def _axis_worker(state: ExecuteAgentState) -> WorkerResult:
    """Axis worker: development-axis layer (decision-driven from intent)."""
    if not _task_enabled(state, "axis"):
        return WorkerResult(worker_type="axis")

    bound_intent = _execution_intent_from_plan(state)
    axes = _intent_list(bound_intent, "development_axes") or _intent_list(bound_intent, "axes")
    if not axes:
        return WorkerResult(
            worker_type="axis",
            unresolved_items=[{
                "code": "axis_output_empty",
                "message": "Axis targets exist but no development-axis layer was produced.",
            }],
        )

    features = []
    unresolved = []
    task_results = []
    axis_tasks_by_target: dict[str, list[Any]] = {}
    for task in _plan_tasks(state, {"axis_construction"}):
        axis_tasks_by_target.setdefault(
            str(_task_value(task, "target_id", "") or ""), []
        ).append(task)
    occurrence_by_target: dict[str, int] = {}
    for axis in axes:
        target_id = str(axis.target_id)
        occurrence = occurrence_by_target.get(target_id, 0)
        occurrence_by_target[target_id] = occurrence + 1
        matching_tasks = axis_tasks_by_target.get(target_id, [])
        matching_task = matching_tasks[min(occurrence, len(matching_tasks) - 1)] if matching_tasks else None
        target_unresolved = []
        errors = []
        target_features = []
        try:
            target_features, reason = materialize_authoritative_axis_lines(
                axis,
                state.spatial_workspace,
            )
            if target_features:
                features.extend(target_features)
            else:
                target_unresolved.append({
                    "code": "axis_source_geometry_unresolved",
                    "target_id": target_id,
                    "reason_code": reason,
                    "message": (
                        "Axis execution requires explicit source_feature_ids and "
                        "authoritative LineString/MultiLineString geometry."
                    ),
                })
        except Exception as e:
            logger.error("[EXECUTE:axis] failed for %s (exception_type=%s)", target_id, type(e).__name__)
            errors.append(f"AXIS_FAILED:{type(e).__name__}")
            target_unresolved.append({
                "code": "axis_failed",
                "target_id": target_id,
                "message": "Axis materialization failed.",
                "exception_type": type(e).__name__,
            })
        unresolved.extend(target_unresolved)
        result = _task_execution_result(
            state,
            "axis_construction",
            target_id,
            task_id=str(_task_value(matching_task, "task_id", "") or "") if matching_task else "",
            candidate_id=str(_task_value(matching_task, "candidate_id", "") or "") if matching_task else "",
            status="succeeded" if target_features else "failed",
            diagnostics=target_unresolved,
            errors=errors,
        )
        if result is not None:
            task_results.append(result)

    layers = [{
        "layerType": "infrastructure",
        "data": {"type": "FeatureCollection", "features": features},
    }] if features else []

    scenario_features = [
        item
        for layer in layers
        for item in _scenario_features_for_layer(
            state, layer, generation_operation="axis_worker"
        )
    ]
    _attach_feature_lineage(task_results, scenario_features)
    return WorkerResult(
        worker_type="axis",
        task_results=task_results,
        layers=layers,
        unresolved_items=unresolved,
        diagnostics=[{"code": "axis_ok", "targets_with_output": len(features)}],
        scenario_features=scenario_features,
        task_id=(
            str(getattr(state.execution_plan.worker_tasks[0], "task_id", ""))
            if state.execution_plan and len(state.execution_plan.worker_tasks) == 1
            else ""
        ),
    )
