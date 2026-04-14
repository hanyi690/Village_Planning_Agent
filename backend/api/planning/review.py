"""
Planning API Review - 审查操作端点

批准、驳回、回滚等审查操作。
"""

import asyncio
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException

from backend.services import PlanningRuntimeService, review_service
from backend.services.sse_manager import sse_manager
from backend.services.checkpoint_service import checkpoint_service
from backend.database.operations_async import get_planning_session_async
from backend.schemas import ReviewActionRequest

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/api/planning/review/{session_id}")
async def review_action(session_id: str, request: ReviewActionRequest):
    """
    处理审查操作

    支持批准、驳回、回滚操作。
    """
    logger.info(f"[Planning API] review_action: session_id={session_id}, action={request.action}")

    try:
        # Rebuild session if needed
        session = sse_manager.get_session(session_id)
        if not session:
            session = await checkpoint_service.rebuild_session_from_db(
                session_id, get_session_async, sse_manager
            )
            if not session:
                raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

        # Get current state
        checkpoint_state = await PlanningRuntimeService.aget_state(session_id)
        if not checkpoint_state or not checkpoint_state.values:
            raise HTTPException(status_code=404, detail=f"Session not found in checkpoint: {session_id}")

        state = checkpoint_state.values
        review_id = state.get("review_id", "")
        is_pause_mode = state.get("pause_after_step", False)

        # Validate pending review
        if not review_id and not is_pause_mode and request.action != "rollback":
            raise HTTPException(status_code=400, detail="No pending review or pause")

        # Handle actions
        if request.action == "approve":
            response = await review_service.approve(session_id, review_id)
            asyncio.create_task(PlanningRuntimeService.resume_execution(session_id))
            return response.model_dump()

        elif request.action == "reject":
            if not request.feedback:
                raise HTTPException(status_code=400, detail="Feedback is required for rejection")

            # 转换图片为 dict 格式
            images_data = []
            if request.images:
                for img in request.images:
                    if hasattr(img, 'model_dump'):
                        images_data.append(img.model_dump())
                    elif hasattr(img, 'dict'):
                        images_data.append(img.dict())
                    elif isinstance(img, dict):
                        images_data.append(img)
                    else:
                        images_data.append(img)

            response = await review_service.reject(
                session_id,
                request.feedback,
                request.dimensions,
                review_id,
                images=images_data,
            )
            asyncio.create_task(PlanningRuntimeService.resume_execution(session_id))
            return response.model_dump()

        elif request.action == "rollback":
            if not request.checkpoint_id:
                raise HTTPException(status_code=400, detail="Checkpoint ID required for rollback")

            response = await review_service.rollback(
                session_id,
                request.checkpoint_id,
                review_id,
            )
            return response.model_dump()

        else:
            raise HTTPException(status_code=400, detail=f"Unknown action: {request.action}")

    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"[Planning API] Review action error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Review action failed: {str(e)}")


__all__ = ["router"]