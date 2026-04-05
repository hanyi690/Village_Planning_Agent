"""
Planning API Module

统一的规划 API 模块，包含所有端点。

模块拆分：
- schemas.py: Request/Response 模型
- startup.py: 启动事件和清理任务
- session.py: 会话管理端点
- stream.py: SSE 流端点
- review.py: 审查操作端点
- dimension.py: 维度相关端点
- message.py: UI 消息端点
- chat.py: 对话端点
- checkpoint.py: 检查点端点
- rate_limit.py: 限流端点
"""

from fastapi import APIRouter

# Import sub-module routers
from .session import router as session_router
from .stream import router as stream_router
from .review import router as review_router
from .dimension import router as dimension_router
from .message import router as message_router
from .chat import router as chat_router
from .checkpoint import router as checkpoint_router
from .rate_limit import router as rate_limit_router

# Import startup functions
from .startup import on_startup, on_shutdown, start_session_cleanup, stop_session_cleanup

# Create main router
router = APIRouter()

# Include all sub-routers
router.include_router(session_router, tags=["Session"])
router.include_router(stream_router, tags=["Stream"])
router.include_router(review_router, tags=["Review"])
router.include_router(dimension_router, tags=["Dimension"])
router.include_router(message_router, tags=["Message"])
router.include_router(chat_router, tags=["Chat"])
router.include_router(checkpoint_router, tags=["Checkpoint"])
router.include_router(rate_limit_router, tags=["RateLimit"])

# Export schemas for convenience
from backend.schemas import (
    StartPlanningRequest,
    ReviewActionRequest,
    ResumeRequest,
    CreateUIMessageRequest,
    ChatMessageRequest,
    RunDimensionsRequest,
    SessionStatusResponse,
)


__all__ = [
    # Router
    "router",
    # Startup
    "on_startup",
    "on_shutdown",
    "start_session_cleanup",
    "stop_session_cleanup",
    # Schemas
    "StartPlanningRequest",
    "ReviewActionRequest",
    "ResumeRequest",
    "CreateUIMessageRequest",
    "ChatMessageRequest",
    "RunDimensionsRequest",
    "SessionStatusResponse",
]