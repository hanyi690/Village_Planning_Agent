"""
Planning API Message - UI 消息端点

用户界面消息的创建和查询。
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException

from backend.database.operations_async import (
    create_ui_message_async,
    get_ui_messages_async,
    upsert_ui_message_async,
    delete_ui_messages_async,
    get_planning_session_async,
)
from backend.schemas import CreateUIMessageRequest

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/api/planning/messages/{session_id}")
async def create_ui_message(session_id: str, request: CreateUIMessageRequest):
    """
    创建/更新 UI 消息 (Upsert)

    根据 message_id 判断是创建新消息还是更新已有消息。
    created_at 在插入时设置，更新时保留原值。
    """
    # Validate PlanningSession exists
    # Ensures message can only be saved for sessions created via /api/planning/start
    db_session = await get_planning_session_async(session_id)
    if not db_session:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    message_created_at = None
    if request.metadata and "created_at" in request.metadata:
        message_created_at = request.metadata["created_at"]

    try:
        message_db_id = await upsert_ui_message_async(
            session_id=session_id,
            message_id=request.message_id,
            role=request.role,
            content=request.content,
            message_type=request.message_type,
            metadata=request.metadata,
            created_at=message_created_at,
        )
        logger.info(f"[Planning API] [{session_id}] UI message upserted: db_id={message_db_id}, message_id={request.message_id}")

        return {
            "success": True,
            "db_id": message_db_id,
            "message_id": request.message_id,
            "session_id": session_id
        }

    except Exception as e:
        logger.error(f"[Planning API] [{session_id}] Failed to create UI message: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/planning/messages/{session_id}")
async def get_ui_messages(
    session_id: str,
    role: Optional[str] = None,
    limit: int = 100
):
    """
    获取 UI 消息列表

    按角色过滤，按时间排序。
    """
    messages = await get_ui_messages_async(session_id, role=role, limit=limit)

    return {
        "success": True,
        "session_id": session_id,
        "messages": messages,
        "count": len(messages)
    }


__all__ = ["router"]