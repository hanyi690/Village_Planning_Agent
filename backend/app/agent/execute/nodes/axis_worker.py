"""Axis worker node: development-axis layer (decision-driven from intent)."""

from __future__ import annotations

from app.agent.execute.execute_state import ExecuteAgentState
from app.agent.execute.nodes.worker_common import _execution_intent_from_plan, _intent_list, _task_enabled, _task_execution_result
from app.modules.schema.contracts.execution_plan_contracts import WorkerResult
from app.utils.logger import get_logger

logger = get_logger(__name__)


def _axis_worker(state: ExecuteAgentState) -> WorkerResult:
    """Axis worker: development-axis layer (decision-driven from intent)."""
    from types import SimpleNamespace

    from app.modules.spatial_ops.geometry.axis_builder import AxisBuilder

    if not _task_enabled(state, "axis"):
        return WorkerResult(worker_type="axis")

    from app.modules.spatial_ops.io import canonical_gis_data_from_workspace

    gis_data = canonical_gis_data_from_workspace(state.spatial_workspace)
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
    for axis in axes:
        target_id = str(axis.target_id)
        target_unresolved = []
        errors = []
        target_features = []
        try:
            axis_layer = AxisBuilder().build(
                intent=SimpleNamespace(axes=[axis], metadata={}),
                boundary_geojson=gis_data.get("boundary_geojson"),
                landuse_current_geojson=gis_data.get("landuse_current_geojson"),
            )
            target_features = list((axis_layer or {}).get("features") or [])
            if target_features:
                for feature in target_features:
                    properties = dict(feature.get("properties") or {})
                    properties["target_id"] = target_id
                    feature["properties"] = properties
                features.extend(target_features)
            else:
                target_unresolved.append({
                    "code": "axis_output_empty",
                    "target_id": target_id,
                    "message": "No development-axis layer was produced for this target.",
                })
        except Exception as e:
            logger.error("[EXECUTE:axis] failed for %s: %s", target_id, e, exc_info=True)
            errors.append(str(e))
            target_unresolved.append({
                "code": "axis_failed",
                "target_id": target_id,
                "message": str(e),
            })
        unresolved.extend(target_unresolved)
        result = _task_execution_result(
            state,
            "axis_construction",
            target_id,
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

    return WorkerResult(
        worker_type="axis",
        task_results=task_results,
        layers=layers,
        unresolved_items=unresolved,
        diagnostics=[{"code": "axis_ok", "targets_with_output": len(features)}],
    )


async def _axis_worker_node(state: ExecuteAgentState) -> dict:
    result = _axis_worker(state)
    return {"worker_results": [result]}
