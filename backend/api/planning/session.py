"""
Planning API Session - 会话管理端点

会话启动、状态查询、删除、恢复等操作。
"""

import asyncio
import logging
from collections import deque
from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel

from backend.schemas import (
    TaskStatus,
    StartPlanningRequest,
    ResumeRequest,
    SessionStatusResponse,
)
from backend.services import (
    PlanningRuntimeService,
    session_service,
    checkpoint_service,
)
from backend.services.rate_limiter import rate_limiter, RateLimiter
from backend.services.sse_manager import sse_manager
from backend.database.operations_async import (
    get_planning_session_async,
    get_ui_messages_async,
)
from src.orchestration.state import state_to_ui_status

logger = logging.getLogger(__name__)
router = APIRouter()


# ============================================
# Rate Limiter Dependency
# ============================================

def get_rate_limiter() -> RateLimiter:
    return rate_limiter


# ============================================
# Session Endpoints
# ============================================

@router.post("/api/planning/start")
async def start_planning(
    request: StartPlanningRequest,
    background_tasks: BackgroundTasks,
    limiter: RateLimiter = Depends(get_rate_limiter)
):
    """
    启动新规划会话

    创建会话并初始化主图，立即返回 session_id 供 SSE 订阅。
    """
    logger.info(f"[Planning API] Start planning: project={request.project_name}")

    # Input validation
    if not request.project_name or not request.project_name.strip():
        raise HTTPException(status_code=400, detail="项目名称不能为空")

    if not request.village_data or len(request.village_data.strip()) < 10:
        raise HTTPException(status_code=400, detail="村庄数据不能为空或过短（至少需要10个字符）")

    # Delegate to PlanningRuntimeService
    result = await PlanningRuntimeService.start_session(
        project_name=request.project_name,
        village_data=request.village_data,
        village_name=request.village_name,
        task_description=request.task_description,
        constraints=request.constraints,
        enable_review=request.enable_review,
        stream_mode=request.stream_mode,
        step_mode=request.step_mode,
        background_tasks=background_tasks,
        rate_limiter=limiter,
    )
    return result


@router.get("/api/planning/status/{session_id}")
async def get_session_status(session_id: str):
    """
    获取会话状态

    使用 Checkpoint 作为单一数据源。
    """
    # Get from database
    db_session = await get_planning_session_async(session_id)
    if not db_session:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    # Get from checkpoint
    checkpoint_state = await PlanningRuntimeService.aget_state(session_id)
    state = dict(checkpoint_state.values) if checkpoint_state and checkpoint_state.values else {}

    # Build UI status
    ui_status = state_to_ui_status(state, db_session)
    ui_status["session_id"] = session_id

    # Extract messages
    messages = []
    raw_messages = state.get("messages", [])
    for msg in raw_messages:
        if hasattr(msg, "content"):
            messages.append({
                "type": msg.__class__.__name__.lower().replace("message", ""),
                "content": msg.content,
                "role": "assistant" if "ai" in msg.__class__.__name__.lower() else "user"
            })
    ui_status["messages"] = messages
    ui_status["ui_messages"] = await get_ui_messages_async(session_id)
    ui_status["revision_history"] = state.get("revision_history", [])
    ui_status["last_checkpoint_id"] = (
        checkpoint_state.config.get("configurable", {}).get("checkpoint_id", "")
        if checkpoint_state else ""
    )

    return ui_status


@router.delete("/api/planning/sessions/{session_id}")
async def delete_session(session_id: str):
    """
    删除会话

    完全删除内存、数据库和检查点数据。
    """
    try:
        result = await session_service.delete_session(session_id)
        logger.info(f"[Planning API] Session {session_id} deleted: {result}")

        return {
            "message": f"Session {session_id} deleted",
            "deleted_checkpoints": result.get("checkpoint", False),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[Planning API] Delete session error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to delete session: {str(e)}")


@router.post("/api/planning/resume")
async def resume_from_checkpoint(request: ResumeRequest):
    """
    从检查点恢复执行
    """
    try:
        session_id = PlanningRuntimeService.generate_session_id()
        logger.info(f"[Planning API] Resuming from checkpoint {request.checkpoint_id}")

        thread_id = request.project_name

        # Find target checkpoint
        target_state = None
        async for state_snapshot in PlanningRuntimeService.aget_state_history(thread_id):
            snapshot_checkpoint_id = state_snapshot.config.get("configurable", {}).get("checkpoint_id", "")
            if snapshot_checkpoint_id == request.checkpoint_id:
                target_state = state_snapshot
                break

        if not target_state:
            raise HTTPException(
                status_code=404,
                detail=f"Checkpoint not found: {request.checkpoint_id}"
            )

        state = target_state.values
        target_layer = state.get("current_layer", 1)

        # Initialize SSE session
        sse_manager.init_session(session_id, {
            "session_id": session_id,
            "project_name": request.project_name,
            "created_at": datetime.now().isoformat(),
            "events": deque(maxlen=5000),
        })

        return {
            "session_id": session_id,
            "status": TaskStatus.running,
            "message": f"Resumed from Layer {target_layer}",
            "stream_url": f"/api/planning/stream/{session_id}",
            "current_layer": target_layer
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[Planning API] Resume error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Resume failed: {str(e)}")


@router.get("/api/planning/sessions/{session_id}/layer/{layer}/reports")
async def get_layer_reports(session_id: str, layer: int):
    """
    获取层级报告
    """
    from backend.services.session_service import session_service

    if layer not in [1, 2, 3]:
        raise HTTPException(status_code=400, detail=f"Invalid layer: {layer}. Must be 1, 2, or 3.")

    db_session = await get_planning_session_async(session_id)
    if not db_session:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    try:
        response = await session_service.get_layer_reports(session_id, layer)
        project_name = await checkpoint_service.get_project_name(session_id)

        return {
            "layer": response.layer,
            "reports": response.reports,
            "report_content": "",
            "project_name": project_name,
            "completed": response.completed,
            "stats": response.stats,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[Planning API] Failed to get layer {layer} reports: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


__all__ = ["router"]