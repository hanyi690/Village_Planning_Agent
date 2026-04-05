"""
Planning API Checkpoint - 检查点端点

检查点列表和历史查询。
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException

from backend.services import PlanningRuntimeService

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

        # Build checkpoint info
        checkpoint = {
            "checkpoint_id": checkpoint_id,
            "project_name": project_name,
            "phase": values.get("phase", "init"),
            "created_at": None,
        }

        # Get timestamp from metadata
        metadata = values.get("metadata", {})
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