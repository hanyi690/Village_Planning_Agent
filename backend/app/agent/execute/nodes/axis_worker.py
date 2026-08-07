"""Axis worker node: development-axis layer (decision-driven from intent)."""

from __future__ import annotations

from app.agent.execute.execute_state import ExecuteAgentState
from app.agent.execute.nodes.worker_common import _intent_list, _task_enabled
from app.modules.schema.contracts.execution_plan_contracts import WorkerResult
from app.utils.logger import get_logger

logger = get_logger(__name__)


def _axis_worker(state: ExecuteAgentState) -> WorkerResult:
    """Axis worker: development-axis layer (decision-driven from intent)."""
    from types import SimpleNamespace

    from app.modules.spatial_ops.geometry.axis_builder import AxisBuilder

    if not _task_enabled(state, "axis"):
        return WorkerResult(worker_type="axis")

    gis_data = state.gis_data or {}
    axes = _intent_list(state.intent, "development_axes") or _intent_list(state.intent, "axes")
    if not axes:
        return WorkerResult(
            worker_type="axis",
            unresolved_items=[{
                "code": "axis_output_empty",
                "message": "Axis targets exist but no development-axis layer was produced.",
            }],
        )

    layers = []
    unresolved = []
    try:
        axis_layer = AxisBuilder().build(
            intent=SimpleNamespace(axes=axes, metadata={}),
            boundary_geojson=gis_data.get("boundary_geojson"),
            landuse_current_geojson=gis_data.get("landuse_current_geojson"),
        )
        if axis_layer and axis_layer.get("features"):
            layers.append({"layerType": "infrastructure", "data": axis_layer})
        else:
            unresolved.append({
                "code": "axis_output_empty",
                "message": "Axis targets exist but no development-axis layer was produced.",
            })
    except Exception as e:
        logger.error("[EXECUTE:axis] failed: %s", e, exc_info=True)
        unresolved.append({"code": "axis_failed", "message": str(e)})

    return WorkerResult(
        worker_type="axis",
        layers=layers,
        unresolved_items=unresolved,
        diagnostics=[{"code": "axis_ok", "layers": len(layers)}],
    )


async def _axis_worker_node(state: ExecuteAgentState) -> dict:
    result = _axis_worker(state)
    return {"worker_results": [result]}