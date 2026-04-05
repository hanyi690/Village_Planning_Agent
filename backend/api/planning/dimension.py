"""
Planning API Dimension - 维度相关端点

维度分析、内容获取、修订历史。
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.services import PlanningRuntimeService, dimension_executor
from backend.services.checkpoint_service import checkpoint_service
from backend.schemas import RunDimensionsRequest

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/api/planning/sessions/{session_id}/dimensions/run")
async def run_dimensions(session_id: str, request: RunDimensionsRequest):
    """
    手动触发维度分析

    并行执行指定维度的分析。
    """
    logger.info(f"[Planning API] [{session_id}] run_dimensions: layer={request.layer}, dims={request.dimension_keys}")

    if request.layer not in [1, 2, 3]:
        raise HTTPException(status_code=400, detail=f"Invalid layer: {request.layer}. Must be 1, 2, or 3.")

    if not request.dimension_keys:
        raise HTTPException(status_code=400, detail="dimension_keys cannot be empty")

    try:
        state = await PlanningRuntimeService.aget_state_values(session_id)
        if not state:
            raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

        results = await dimension_executor.execute_dimensions(
            session_id=session_id,
            layer=request.layer,
            dimension_keys=request.dimension_keys,
            state=state
        )

        await dimension_executor.update_reports(session_id, request.layer, results)

        return {
            "success": True,
            "session_id": session_id,
            "layer": request.layer,
            "results": results
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[Planning API] [{session_id}] run_dimensions failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Dimension execution failed: {str(e)}")


@router.get("/api/planning/sessions/{session_id}/dimensions/{dimension_key}")
async def get_dimension_content(session_id: str, dimension_key: str):
    """
    获取单个维度内容

    从 Checkpoint 获取维度的最新内容。
    """
    state = await PlanningRuntimeService.aget_state_values(session_id)
    if not state:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    # Find dimension in reports
    reports = state.get("reports", {})
    dimension_name = ""
    content = ""
    layer = 0

    for layer_key, layer_reports in reports.items():
        if dimension_key in layer_reports:
            content = layer_reports[dimension_key]
            layer = int(layer_key.replace("layer", ""))
            break

    # Get dimension name
    from src.orchestration.nodes.dimension_node import DIMENSION_NAMES
    dimension_name = DIMENSION_NAMES.get(dimension_key, dimension_key)

    # Get completion status
    completed_dims = state.get("completed_dimensions", {})
    layer_key = f"layer{layer}"
    is_completed = dimension_key in completed_dims.get(layer_key, [])

    return {
        "session_id": session_id,
        "dimension_key": dimension_key,
        "dimension_name": dimension_name,
        "layer": layer,
        "content": content,
        "completed": is_completed,
        "timestamp": datetime.now().isoformat()
    }


@router.get("/api/planning/sessions/{session_id}/dimensions/{dimension_key}/revisions")
async def get_dimension_revisions(session_id: str, dimension_key: str, limit: int = 20):
    """
    获取维度修订历史
    """
    history = await checkpoint_service.get_checkpoint_history(session_id)

    revisions = []
    for snapshot in history:
        values = snapshot.get("values", {})
        reports = values.get("reports", {})

        for layer_key, layer_reports in reports.items():
            if dimension_key in layer_reports:
                revisions.append({
                    "checkpoint_id": snapshot.get("checkpoint_id", ""),
                    "content": layer_reports[dimension_key],
                    "timestamp": values.get("metadata", {}).get("last_signal_timestamp", ""),
                })

                if len(revisions) >= limit:
                    break

        if len(revisions) >= limit:
            break

    return {
        "session_id": session_id,
        "dimension_key": dimension_key,
        "revisions": revisions,
        "total": len(revisions)
    }


__all__ = ["router"]