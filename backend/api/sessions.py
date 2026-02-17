"""
Sessions API endpoints - UI session management
会话API端点 - UI会话管理
"""

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from typing import Dict, Optional, List, Literal
from pydantic import BaseModel, Field
import uuid
import asyncio
import json
from datetime import datetime
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from schemas import ConversationMessage, ConversationState
from services.shared_task_manager import task_manager

router = APIRouter()

# Constants
WELCOME_MESSAGE = """👋 欢迎使用村庄规划智能体！

我可以帮您:
• 创建村庄规划方案
• 分析村庄现状数据
• 生成规划思路和详细方案
• 根据反馈修改规划

请上传村庄现状数据文件，或直接告诉我村庄名称和信息。"""

# Global session storage
sessions: Dict[str, ConversationState] = {}


# ============================================
# Request Schemas
# ============================================

class CreateSessionRequest(BaseModel):
    """Session creation request"""
    session_type: Literal["conversation", "form", "cli", "api"] = Field(default="conversation", description="会话类型")


class LinkTaskRequest(BaseModel):
    """Link session to task request"""
    task_id: str = Field(..., description="任务ID")


class AddMessageRequest(BaseModel):
    """Add message request"""
    role: Literal["user", "assistant", "system"] = Field(..., description="消息角色")
    content: str = Field(..., description="消息内容")
    message_type: Literal["text", "file", "progress", "action", "result", "error", "system"] = Field(
        default="text", description="消息类型"
    )
    metadata: Optional[Dict] = Field(None, description="额外元数据")


class SessionResponse(BaseModel):
    """Session response model"""
    session_id: str
    session_type: str
    status: str
    message: Optional[str] = None


# ============================================
# Helper Functions
# ============================================

def get_session(session_id: str) -> Optional[ConversationState]:
    """Get session by ID"""
    return sessions.get(session_id)


def create_session(session_id: str, session_type: str) -> ConversationState:
    """Create a new session"""
    conv = ConversationState(conversation_id=session_id, status="idle")
    sessions[session_id] = conv
    return conv


def create_message(role: str, content: str, message_type: str = "text", **kwargs) -> ConversationMessage:
    """Create a conversation message with common fields"""
    return ConversationMessage(
        role=role,
        content=content,
        message_type=message_type,
        timestamp=datetime.now(),
        **kwargs,
    )


def handle_api_error(error: Exception, context: str) -> HTTPException:
    """Standardized error handler"""
    import traceback
    print(f"[ERROR] {context}: {str(error)}", file=sys.stderr)
    print(traceback.format_exc(), file=sys.stderr)
    return HTTPException(status_code=500, detail=f"{context}失败: {str(error)}")


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

        # Add welcome message for conversation sessions
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
        raise handle_api_error(e, "创建会话")


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

    # Only allow deletion if not linked to an active task
    if session.task_id:
        task_info = task_manager.get_task(session.task_id)
        if task_info and task_info["status"] in ["pending", "running", "paused", "reviewing", "revising"]:
            raise HTTPException(
                status_code=400,
                detail="无法删除关联到活动任务的会话"
            )

    del sessions[session_id]
    return {"message": f"会话已删除: {session_id}"}


@router.get("")
async def list_sessions():
    """
    List all sessions
    列出所有会话
    """
    return {
        "total": len(sessions),
        "sessions": [
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
        ],
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

        # Add user message
        user_message = create_message(
            request.role,
            request.content,
            request.message_type,
            metadata=request.metadata
        )
        session.messages.append(user_message)
        session.updated_at = datetime.now()

        return {
            "success": True,
            "message": "消息已添加",
            "message_id": str(uuid.uuid4()),
        }
    except HTTPException:
        raise
    except Exception as e:
        raise handle_api_error(e, "添加消息")


@router.post("/{session_id}/link")
async def link_to_task(session_id: str, request: LinkTaskRequest):
    """
    Link session to a task
    关联会话到任务
    """
    try:
        session = get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail=f"会话不存在: {session_id}")

        # Verify task exists
        task_info = task_manager.get_task(request.task_id)
        if not task_info:
            raise HTTPException(status_code=404, detail=f"任务不存在: {request.task_id}")

        # Link session to task
        session.task_id = request.task_id
        session.project_name = task_info.get("request", {}).get("project_name")
        session.status = "planning"
        session.updated_at = datetime.now()

        # Add system message
        session.messages.append(
            create_message(
                "system",
                f"🚀 规划任务已启动\n\n任务ID: {request.task_id}\n村庄: {session.project_name}",
                "system",
                task_id=request.task_id,
            )
        )

        return {
            "success": True,
            "task_id": request.task_id,
            "session_id": session_id,
            "status": "planning",
            "message": f"会话已关联到任务: {request.task_id}",
        }
    except HTTPException:
        raise
    except Exception as e:
        raise handle_api_error(e, "关联任务")


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

            # If session is linked to a task, stream task updates
            if session.task_id:
                task_info = task_manager.get_task(session.task_id)
                if task_info:
                    event_data = {
                        "type": "task_update",
                        "session_id": session_id,
                        "task_id": session.task_id,
                        "data": {
                            "status": task_info["status"],
                            "progress": task_info.get("progress", 0),
                            "current_layer": task_info.get("current_layer"),
                            "message": task_info.get("message", ""),
                            "updated_at": task_info["updated_at"].isoformat(),
                        }
                    }

                    # Handle terminal states
                    if task_info["status"] in ("completed", "failed"):
                        if task_info["status"] == "completed":
                            event_data["type"] = "complete"
                            event_data["data"]["result"] = task_info.get("result")
                        else:
                            event_data["type"] = "failed"
                            event_data["data"]["error"] = task_info.get("error")
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
