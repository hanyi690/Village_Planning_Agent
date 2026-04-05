"""
Planning API Checkpoint - 检查点端点

检查点列表和历史查询。
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException

from backend.services import PlanningRuntimeService
from src.orchestration.state import _phase_to_layer

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/api/planning/checkpoints/{project_name}")
async def list_checkpoints(project_name: str, session_id: Optional[str] = None):
    """
    列出项目的所有检查点

    从 LangGraph Checkpoint 获取检查点历史。
    """
    thread_id = session_id or project_name

    logger.info(f"[Checkpoints] list_checkpoints: project_name={project_name}, session_id={session_id}")

    checkpoints = []
    async for state_snapshot in PlanningRuntimeService.aget_state_history(thread_id):
        checkpoint_id = state_snapshot.config.get("configurable", {}).get("checkpoint_id", "")

        if not checkpoint_id:
            continue

        values = state_snapshot.values or {}
        metadata = values.get("metadata", {})

        # Build checkpoint info
        phase = values.get("phase", "init")
        # Use existing _phase_to_layer; for "completed", show layer 3 (final report)
        layer = _phase_to_layer(phase)
        if layer is None:
            layer = 3  # completed phase maps to layer 3 for UI display

        checkpoint = {
            "checkpoint_id": checkpoint_id,
            "project_name": project_name,
            "phase": phase,
            "created_at": None,
            "type": metadata.get("checkpoint_type", "regular"),
            "layer": layer,
        }

        # Get timestamp from metadata
        if metadata.get("last_signal_timestamp"):
            checkpoint["created_at"] = metadata["last_signal_timestamp"]

        # Get layer completion status
        completed_dims = values.get("completed_dimensions", {})
        checkpoint["layers"] = {
            "layer1": len(completed_dims.get("layer1", [])),
            "layer2": len(completed_dims.get("layer2", [])),
            "layer3": len(completed_dims.get("layer3", [])),
        }

        checkpoints.append(checkpoint)

    return {
        "project_name": project_name,
        "checkpoints": checkpoints,
        "total": len(checkpoints)
    }


__all__ = ["router"]