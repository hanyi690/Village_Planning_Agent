"""
Sessions API endpoints - UI session management
会话API端点 - UI会话管理

This API manages UI-specific sessions (conversations, form submissions).
It does NOT create planning sessions - use /api/planning/start for that.
此API管理UI特定的会话（对话、表单提交）。
不创建规划会话 - 请使用 /api/planning/start 创建规划会话。
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from backend.schemas import ConversationMessage, ConversationState
from backend.utils.error_handler import handle_api_error
from backend.database import (
    create_ui_session,
    get_ui_session,
    update_ui_session,
    delete_ui_session,
    list_ui_sessions,
    create_ui_message,
    get_ui_messages,
    delete_ui_messages,
)

router = APIRouter()
logger = logging.getLogger(__name__)

# Constants
WELCOME_MESSAGE = """👋 欢迎使用村庄规划智能体！

我可以帮您:
• 创建村庄规划方案
• 分析村庄现状数据
• 生成规划思路和详细方案
• 根据反馈修改规划

请上传村庄现状数据文件，或直接告诉我村庄名称和信息。"""

# Global UI session storage (for backward compatibility, backed by database)
sessions: dict[str, ConversationState] = {}
USE_DATABASE_PERSISTENCE = True


# ============================================
# Request Schemas
# ============================================

class CreateSessionRequest(BaseModel):
    """Session creation request"""
    session_type: str = Field(
        default="conversation",
        description="会话类型",
        pattern="^(conversation|form|cli|api)$"
    )


class LinkTaskRequest(BaseModel):
    """Link session to task request"""
    task_id: str = Field(..., description="任务ID")


class AddMessageRequest(BaseModel):
    """Add message request"""
    role: str = Field(..., description="消息角色", pattern="^(user|assistant|system)$")
    content: str = Field(..., description="消息内容")
    message_type: str = Field(
        default="text",
        description="消息类型",
        pattern="^(text|file|progress|action|result|error|system)$"
    )
    metadata: dict[str, Any] | None = Field(None, description="额外元数据")


class SessionResponse(BaseModel):
    """Session response model"""
    session_id: str
    session_type: str
    status: str
    message: str | None = None


# ============================================
# Helper Functions
# ============================================

def get_session(session_id: str) -> ConversationState | None:
    """Get session by ID"""
    return sessions.get(session_id)


def create_session(session_id: str, session_type: str) -> ConversationState:
    """Create a new session"""
    conv = ConversationState(conversation_id=session_id, status="idle")
    sessions[session_id] = conv

    if USE_DATABASE_PERSISTENCE:
        try:
            create_ui_session(session_id, session_type)
        except Exception as e:
            logger.error(f"Failed to create UI session in database: {e}")

    return conv


def create_message(
    role: str,
    content: str,
    message_type: str = "text",
    **kwargs
) -> ConversationMessage:
    """Create a conversation message with common fields"""
    return ConversationMessage(
        role=role,
        content=content,
        message_type=message_type,
        timestamp=datetime.now(),
        **kwargs,
    )


# ============================================
# Session Endpoints
# ============================================

@router.post("", response_model=SessionResponse)
async def create_new_session(request: CreateSessionRequest = CreateSessionRequest()):
    """
    Create a new session
    创建新会话
    """
    try:
        session_id = str(uuid.uuid4())
        session = create_session(session_id, request.session_type)

        if request.session_type == "conversation":
            session.messages.append(create_message("assistant", WELCOME_MESSAGE))

        session.updated_at = datetime.now()

        return SessionResponse(
            session_id=session_id,
            session_type=request.session_type,
            status="idle",
            message="会话已创建",
        )
    except Exception as e:
        raise handle_api_error(e, "创建会话", status_code=500)


@router.get("/{session_id}")
async def get_session_state(session_id: str):
    """
    Get session state
    获取会话状态
    """
    session = get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"会话不存在: {session_id}")
    return session


@router.delete("/{session_id}")
async def delete_session(session_id: str):
    """
    Delete a session
    删除会话
    """
    session = get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"会话不存在: {session_id}")

    del sessions[session_id]

    if USE_DATABASE_PERSISTENCE:
        try:
            delete_ui_messages(session_id)
            delete_ui_session(session_id)
        except Exception as e:
            logger.error(f"Failed to delete UI session from database: {e}")

    return {"message": f"会话已删除: {session_id}"}


@router.get("")
async def list_sessions():
    """
    List all sessions
    列出所有会话
    """
    session_list = [
        {
            "session_id": session_id,
            "status": session.status,
            "project_name": session.project_name,
            "task_id": session.task_id,
            "message_count": len(session.messages),
            "created_at": session.created_at.isoformat(),
            "updated_at": session.updated_at.isoformat(),
        }
        for session_id, session in sessions.items()
    ]

    return {
        "total": len(session_list),
        "sessions": session_list,
    }


@router.post("/{session_id}/messages")
async def add_message(session_id: str, request: AddMessageRequest):
    """
    Add a message to the session
    添加消息到会话
    """
    try:
        session = get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail=f"会话不存在: {session_id}")

        user_message = create_message(
            request.role,
            request.content,
            request.message_type,
            metadata=request.metadata
        )
        session.messages.append(user_message)
        session.updated_at = datetime.now()

        if USE_DATABASE_PERSISTENCE:
            try:
                create_ui_message(
                    session_id=session_id,
                    role=request.role,
                    content=request.content,
                    message_type=request.message_type,
                    metadata=request.metadata
                )
            except Exception as e:
                logger.error(f"Failed to save message to database: {e}")

        return {
            "success": True,
            "message": "消息已添加",
            "message_id": str(uuid.uuid4()),
        }
    except HTTPException:
        raise
    except Exception as e:
        raise handle_api_error(e, "添加消息", status_code=500)


@router.post("/{session_id}/link")
async def link_to_task(session_id: str, request: LinkTaskRequest):
    """
    Link UI session to a planning task
    关联UI会话到规划任务

    Note: This does NOT create the planning task.
    Use POST /api/planning/start to create planning tasks.
    """
    try:
        session = get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail=f"会话不存在: {session_id}")

        session.task_id = request.task_id
        session.status = "planning"
        session.updated_at = datetime.now()

        session.messages.append(
            create_message(
                "system",
                f"🚀 规划任务已启动\n\n任务ID: {request.task_id}\n可以通过 /api/planning/stream/{request.task_id} 查看实时进度",
                "system",
                task_id=request.task_id,
            )
        )

        return {
            "success": True,
            "task_id": request.task_id,
            "session_id": session_id,
            "status": "planning",
            "message": f"UI会话已关联到规划任务: {request.task_id}",
        }
    except HTTPException:
        raise
    except Exception as e:
        raise handle_api_error(e, "关联任务", status_code=500)


@router.get("/{session_id}/stream")
async def stream_session_updates(session_id: str):
    """
    Stream session updates using SSE
    使用SSE流式传输会话更新
    """
    if not get_session(session_id):
        raise HTTPException(status_code=404, detail=f"会话不存在: {session_id}")

    async def event_generator():
        while True:
            session = get_session(session_id)
            if not session:
                yield f"data: {json.dumps({'error': 'Session not found'})}\n\n"
                break

            if session.task_id:
                event_data = {
                    "type": "session_update",
                    "session_id": session_id,
                    "data": {
                        "status": session.status,
                        "message_count": len(session.messages),
                        "updated_at": session.updated_at.isoformat(),
                    }
                }

                if session.status in ("completed", "failed"):
                    event_data["type"] = session.status
                    yield f"data: {json.dumps(event_data)}\n\n"
                    break

                yield f"data: {json.dumps(event_data)}\n\n"

            await asyncio.sleep(1)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
