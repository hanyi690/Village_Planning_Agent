"""
Unified Planning API - Simplified Architecture (No BackgroundTaskManager)

This API consolidates tasks.py and orchestration.py into a single, clean interface.
Uses FastAPI BackgroundTasks for non-blocking execution.

Endpoints:
- POST /api/planning/start - Create and start planning session
- GET /api/planning/stream/{session_id} - SSE streaming
- POST /api/planning/review/{session_id} - Review actions (approve/reject/rollback)
- GET /api/planning/status/{session_id} - Session status
- DELETE /api/planning/sessions/{session_id} - Delete session

NOTE: This file is being gradually migrated to services/planning_service.py
See: backend/services/planning_service.py, backend/services/sse_manager.py
"""

import asyncio
import logging
import sys
import time
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from langchain_core.messages import HumanMessage
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from typing_extensions import Annotated

from src.core.config import (
    DEFAULT_TASK_DESCRIPTION,
    DEFAULT_CONSTRAINTS,
    DEFAULT_ENABLE_REVIEW,
    DEFAULT_STREAM_MODE,
    DEFAULT_STEP_MODE,
)

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from backend.api.tool_manager import tool_manager, ToolManager
from backend.schemas import TaskStatus
from backend.services.rate_limiter import rate_limiter, RateLimiter
from backend.services.sse_manager import sse_manager
from backend.services.planning_service import planning_service
from backend.utils.progress_helper import calculate_progress
from backend.utils.logging import _extract_session_id
from src.orchestration.main_graph import create_unified_planning_graph
from src.orchestration.state import get_layer_dimensions

from src.utils.paths import get_results_dir

# ✅ 导入异步数据库操作
from backend.database.operations_async import (
    add_session_event_async as add_event_async,
    get_session_events_async as get_events_async,
    create_planning_session_async as create_session_async,
    get_planning_session_async as get_session_async,
    update_planning_session_async as update_session_async,
    delete_planning_session_async as delete_session_async,
    # UI 消息存储操作
    create_ui_message_async,
    get_ui_messages_async,
    upsert_ui_message_async,  # ✅ 新增：upsert 消息
    delete_ui_messages_async,
)
# Import database path and checkpointer from engine
from backend.database.engine import get_db_path, get_global_checkpointer

router = APIRouter()

logger = logging.getLogger(__name__)


# ============================================
# 🔧 Dependency Injection - FastAPI 最佳实践
# ============================================

def get_rate_limiter() -> RateLimiter:
    """
    获取 RateLimiter 实例的依赖注入函数

    使用 FastAPI 的 Depends 模式进行依赖注入，便于单元测试和依赖管理。

    Returns:
        RateLimiter: 全局限流器实例
    """
    return rate_limiter


def get_tool_manager() -> ToolManager:
    """
    获取 ToolManager 实例的依赖注入函数

    使用 FastAPI 的 Depends 模式进行依赖注入，便于单元测试和依赖管理。

    Returns:
        ToolManager: 全局工具管理器实例
    """
    return tool_manager


# 类型别名：用于端点参数的便捷类型注解
RateLimiterDep = Annotated[RateLimiter, Depends(get_rate_limiter)]
ToolManagerDep = Annotated[ToolManager, Depends(get_tool_manager)]


# ============================================
# 🔧 Startup Event - 保存主事件循环引用
# ============================================
@router.on_event("startup")
async def _save_main_event_loop():
    """
    在应用启动时保存主事件循环引用

    这样可以在 LLM 回调的同步线程中安全地发布 SSE 事件
    """
    global _main_event_loop
    _main_event_loop = asyncio.get_running_loop()
    # 同时初始化 sse_manager 的事件循环
    sse_manager.save_event_loop(_main_event_loop)
    logger.info("[SSE] 主事件循环已保存，跨线程事件发布已启用")


# Configuration constants
MAX_SESSION_EVENTS = 5000  # Maximum events to keep per session (增加容量以支持更长的规划会话)
EVENT_CLEANUP_INTERVAL_SECONDS = 300  # Cleanup interval: 5 minutes (instead of 1 hour)

# ============================================
# State Management - SSEManager (SSOT)
# ============================================
# All state is now managed by SSEManager.
# Use SSEManager's public methods instead of accessing internal attributes:
# - sse_manager.get_session() / get_session_events() / append_event()
# - sse_manager.get_subscriber_count() / subscribe() / unsubscribe()
# - sse_manager.is_execution_active() / set_execution_active()
# - sse_manager.get_stream_state() / set_stream_state()


# ============================================
# Session Cleanup Background Task
# ============================================

# Session TTL configuration
SESSION_TTL_HOURS = 24  # 会话过期时间（小时）

# Cleanup task management
_cleanup_task: Optional[asyncio.Task] = None
_cleanup_running = False


async def start_session_cleanup() -> None:
    """
    启动会话清理后台任务
    
    定期清理过期的内存状态，防止长期运行导致无用状态堆积。
    """
    global _cleanup_task, _cleanup_running
    
    if _cleanup_running:
        logger.warning("[Session Cleanup] 清理任务已在运行中")
        return
    
    _cleanup_running = True
    _cleanup_task = asyncio.create_task(_session_cleanup_loop())
    logger.info(f"[Session Cleanup] 🧹 会话清理后台任务已启动 (TTL: {SESSION_TTL_HOURS}h, 间隔: {EVENT_CLEANUP_INTERVAL_SECONDS}s)")


async def stop_session_cleanup() -> None:
    """
    停止会话清理后台任务
    """
    global _cleanup_task, _cleanup_running
    
    if not _cleanup_running or _cleanup_task is None:
        return
    
    _cleanup_running = False
    
    try:
        _cleanup_task.cancel()
        await _cleanup_task
    except asyncio.CancelledError:
        pass
    
    _cleanup_task = None
    logger.info("[Session Cleanup] 🧹 会话清理后台任务已停止")


async def _session_cleanup_loop() -> None:
    """
    Session cleanup loop

    Periodically cleans expired sessions and orphan states.
    All cleanup logic is delegated to SSEManager.cleanup_expired_sessions().
    """
    from datetime import timedelta

    logger.info("[Session Cleanup] Cleanup loop started")

    while _cleanup_running:
        try:
            await asyncio.sleep(EVENT_CLEANUP_INTERVAL_SECONDS)

            if not _cleanup_running:
                break

            now = datetime.now()
            cutoff_time = now - timedelta(hours=SESSION_TTL_HOURS)

            # Delegate cleanup to SSEManager
            cleaned = sse_manager.cleanup_expired_sessions(cutoff_time)

            total_cleaned = sum(cleaned.values())
            if total_cleaned == 0:
                logger.debug(f"[Session Cleanup] No cleanup needed (active sessions: {sse_manager.get_session_count()})")

        except asyncio.CancelledError:
            logger.info("[Session Cleanup] Cleanup loop cancelled")
            break
        except Exception as e:
            logger.error(f"[Session Cleanup] Cleanup loop error: {e}", exc_info=True)
            await asyncio.sleep(60)  # Wait 1 minute before retry on error


# ============================================
# Request/Response Schemas
# ============================================

class StartPlanningRequest(BaseModel):
    """Request to start planning session"""
    project_name: str = Field(..., description="项目名称/村庄名称")
    village_data: str = Field(..., description="村庄现状数据")
    task_description: str = Field(default=DEFAULT_TASK_DESCRIPTION, description="规划任务描述")
    constraints: str = Field(default=DEFAULT_CONSTRAINTS, description="规划约束条件")
    enable_review: bool = Field(default=DEFAULT_ENABLE_REVIEW, description="启用人工审查")
    step_mode: bool = Field(default=DEFAULT_STEP_MODE, description="步进模式（每层暂停）")
    stream_mode: bool = Field(default=DEFAULT_STREAM_MODE, description="启用流式输出（token级实时传输）")


class ReviewActionRequest(BaseModel):
    """Request for review action"""
    action: str = Field(..., description="Action: approve | reject | rollback")
    feedback: Optional[str] = Field(None, description="反馈内容（驳回时必填）")
    dimensions: Optional[List[str]] = Field(None, description="审查维度")
    checkpoint_id: Optional[str] = Field(None, description="目标检查点ID（回退时必填）")


class ResumeRequest(BaseModel):
    """Request to resume from checkpoint"""
    checkpoint_id: str = Field(..., description="检查点ID")
    project_name: str = Field(..., description="项目名称")


class CreateUIMessageRequest(BaseModel):
    """Request to create a UI message"""
    message_id: str = Field(..., description="Frontend message ID (unique identifier for upsert)")
    role: str = Field(..., description="Message role: user | assistant | system")
    content: str = Field(..., description="Message content")
    message_type: str = Field(default="text", description="Message type: text | file | progress | layer_completed | dimension_report")
    metadata: Optional[Dict[str, Any]] = Field(default=None, description="Additional message metadata")


class ChatMessageRequest(BaseModel):
    """Request to send a chat message to planning session"""
    message: str = Field(..., description="用户消息内容")


class SessionStatusResponse(BaseModel):
    """Session status response"""
    session_id: str
    status: str
    current_layer: Optional[int] = None
    previous_layer: Optional[int] = None  # 刚完成的层级（待审查层级）
    created_at: str
    progress: Optional[float] = None
    layer_1_completed: bool = False
    layer_2_completed: bool = False
    layer_3_completed: bool = False
    pause_after_step: bool = False
    execution_complete: bool = False
    execution_error: Optional[str] = None


# ============================================
# Helper Functions
# ============================================

def _append_session_event(session_id: str, event: Dict) -> int:
    """
    Thread-safe append event to session events list.

    Delegates to sse_manager for event storage and publishing.

    Args:
        session_id: Session identifier
        event: Event dictionary to append

    Returns:
        The event_id assigned to this event, or -1 if failed
    """
    # Use sse_manager for storage
    count = sse_manager.append_event(session_id, event)

    # Publish to subscribers
    sse_manager.publish_sync(session_id, event)

    return count


# ============================================
# ✅ 新增：异步版本的事件追加函数
# ============================================

async def _append_session_event_async(session_id: str, event: Dict) -> bool:
    """
    异步版本的会话事件追加（高性能）

    Uses async database operations and delegates to sse_manager.

    Args:
        session_id: Session identifier
        event: Event dictionary to append

    Returns:
        True: 成功, False: 失败
    """
    try:
        # Store to database
        success = await add_event_async(session_id, event)
        if success:
            logger.debug(f"[Async DB] Event appended to session {session_id}")
            # Update sse_manager cache
            sse_manager.append_event(session_id, event)
            # Publish to subscribers
            sse_manager.publish_sync(session_id, event)
        return success
    except Exception as e:
        logger.error(f"[Async DB] Failed to append event: {e}", exc_info=True)
        # Fallback to sse_manager
        sse_manager.append_event(session_id, event)
        sse_manager.publish_sync(session_id, event)
        return False


# ============================================
# Tool SSE Events - 从 sse_publisher 重新导出
# ============================================

# 从 sse_publisher 导入工具事件函数，保持向后兼容
from src.utils.sse_publisher import (
    append_dimension_complete_event,
    append_tool_call_event,
    append_tool_progress_event,
    append_tool_result_event,
    TOOL_STATUS_RUNNING,
    TOOL_STATUS_SUCCESS,
    TOOL_STATUS_ERROR,
)


# ============================================
# 🔧 asyncio.Queue 订阅管理系统
# ============================================

async def _rebuild_events_from_checkpoint(session_id: str) -> List[Dict[str, Any]]:
    """
    从 Checkpoint 重建关键事件
    
    当内存 _sessions 中没有历史事件时（如服务重启后），
    从 LangGraph Checkpoint 读取状态并重建 layer_completed 和 pause 事件。
    
    Args:
        session_id: 会话 ID
        
    Returns:
        重建的事件列表
    """
    events = []
    
    try:
        # ✅ 修复：使用正确的函数获取 checkpointer 和创建 graph
        checkpointer = await get_global_checkpointer()
        if not checkpointer:
            logger.warning(f"[Checkpoint Rebuild] Session {session_id}: checkpointer 不可用")
            return events
        
        graph = create_unified_planning_graph(checkpointer=checkpointer)
        if not graph:
            logger.warning(f"[Checkpoint Rebuild] Session {session_id}: graph 创建失败")
            return events
        
        config = {"configurable": {"thread_id": session_id}}
        checkpoint_state = await graph.aget_state(config)
        
        if not checkpoint_state or not checkpoint_state.values:
            logger.debug(f"[Checkpoint Rebuild] Session {session_id}: 无 Checkpoint 状态")
            return events
        
        state = checkpoint_state.values
        
        # 获取已发送的层级列表
        metadata = state.get("metadata", {})
        published_layers = set(metadata.get("published_layers", []))
        
        # Rebuild layer_completed events with NEW Schema
        reports = state.get("reports", {})
        completed_dims = state.get("completed_dimensions", {})
        phase = state.get("phase", "init")

        for layer_num in [1, 2, 3]:
            layer_key = f"layer{layer_num}"
            layer_completed = len(completed_dims.get(layer_key, [])) >= len(get_layer_dimensions(layer_num))

            if layer_completed:
                dimension_reports = reports.get(layer_key, {})
                total_chars = sum(len(v) for v in dimension_reports.values()) if dimension_reports else 0

                event = {
                    "type": "layer_completed",
                    "layer": layer_num,
                    "layer_number": layer_num,
                    "session_id": session_id,
                    "message": f"Layer {layer_num} completed",
                    "has_data": len(dimension_reports) > 0 and total_chars > 0,
                    "dimension_count": len(dimension_reports) if dimension_reports else 0,
                    "total_chars": total_chars,
                    "pause_after_step": state.get("pause_after_step", False),
                    "phase": phase,
                    "timestamp": metadata.get("last_signal_timestamp", datetime.now().isoformat()),
                    "_rebuild": True,
                }
                events.append(event)
                logger.info(f"[Checkpoint Rebuild] Session {session_id}: 重建 layer_completed 事件 Layer {layer_num}")
        
        # 重建 pause 事件
        if state.get("pause_after_step", False):
            previous_layer = state.get("previous_layer", 1)
            # ✅ 从 checkpoint 配置中获取真实的 checkpoint_id
            checkpoint_id = checkpoint_state.config.get("configurable", {}).get("checkpoint_id", "")
            pause_event = {
                "type": "pause",
                "session_id": session_id,
                "current_layer": previous_layer,
                "checkpoint_id": checkpoint_id,
                "reason": "step_mode",
                "timestamp": datetime.now().isoformat(),
                "_rebuild": True,
            }
            events.append(pause_event)
            logger.info(f"[Checkpoint Rebuild] Session {session_id}: 重建 pause 事件 Layer {previous_layer}")
        
        logger.info(f"[Checkpoint Rebuild] Session {session_id}: 共重建 {len(events)} 个事件")
        
    except Exception as e:
        logger.error(f"[Checkpoint Rebuild] Session {session_id}: 重建失败 - {e}", exc_info=True)
    
    return events


async def subscribe_session(session_id: str) -> asyncio.Queue:
    """
    订阅 session 的事件流，返回专用的 asyncio.Queue

    Delegates to sse_manager for subscription with historical event sync.

    Args:
        session_id: 会话 ID

    Returns:
        asyncio.Queue: 专用于该连接的事件队列
    """
    queue = await sse_manager.subscribe(session_id)

    # Check if we need to rebuild from checkpoint
    historical_events = sse_manager.get_events_copy(session_id)
    layer_completed_found = any(e.get("type") == "layer_completed" for e in historical_events)

    if len(historical_events) == 0 or not layer_completed_found:
        logger.info(f"[SSE Subscribe] Session {session_id}: Rebuilding from checkpoint")
        rebuilt_events = await _rebuild_events_from_checkpoint(session_id)

        if rebuilt_events:
            for event in rebuilt_events:
                try:
                    queue.put_nowait(event)
                    sse_manager.append_event(session_id, event)
                except asyncio.QueueFull:
                    logger.warning(f"[SSE Subscribe] Session {session_id}: Queue full, dropping rebuilt event")
                    break

    return queue


async def _is_execution_active(session_id: str) -> bool:
    """
    检查执行是否活跃 (从数据库读取)
    
    ✅ SSOT 简化：不再使用内存 _active_executions，直接从数据库读取
    
    Args:
        session_id: Session identifier

    Returns:
        True if execution is active
    """
    from backend.database.operations_async import is_execution_active_async
    return await is_execution_active_async(session_id)


async def _set_execution_active(session_id: str, active: bool) -> None:
    """
    设置执行活跃状态 (写入数据库)
    
    ✅ SSOT 简化：不再使用内存 _active_executions，直接写入数据库
    
    Args:
        session_id: Session identifier
        active: Active state to set
    """
    from backend.database.operations_async import set_execution_active_async
    await set_execution_active_async(session_id, active)


async def _get_stream_state(session_id: str) -> str:
    """
    获取流状态 (从数据库读取)
    
    ✅ SSOT 简化：不再使用内存 _stream_states，直接从数据库读取
    
    Args:
        session_id: Session identifier

    Returns:
        Stream state: "active", "paused", or "completed"
    """
    from backend.database.operations_async import get_stream_state_async
    return await get_stream_state_async(session_id)


async def _set_stream_state(session_id: str, state: str) -> None:
    """
    设置流状态 (写入数据库)
    
    ✅ SSOT 简化：不再使用内存 _stream_states，直接写入数据库
    
    Args:
        session_id: Session identifier
        state: New stream state
    """
    from backend.database.operations_async import set_stream_state_async
    await set_stream_state_async(session_id, state)


def _generate_session_id() -> str:
    """Generate session ID (timestamp format)"""
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _get_session_path(project_name: str, session_id: str) -> Path:
    """Get file system path for session"""
    safe_name = project_name.replace('/', '_').replace('\\', '_').replace(':', '_')
    return get_results_dir() / safe_name / session_id


def _validate_resume_state(state: Dict[str, Any], phase: str) -> bool:
    """
    Validate that required state is present for resume - NEW Schema

    Args:
        state: Current state dictionary
        phase: Current phase to resume from

    Returns:
        True if state is valid for resume
    """
    reports = state.get("reports", {})
    completed_dims = state.get("completed_dimensions", {})

    if phase == "layer2":
        # Need Layer 1 data (reports.layer1)
        layer1_reports = reports.get("layer1", {})
        layer1_completed = len(completed_dims.get("layer1", [])) >= len(get_layer_dimensions(1))
        return bool(layer1_reports) and layer1_completed
    elif phase == "layer3":
        # Need Layer 1 and 2 data
        layer1_reports = reports.get("layer1", {})
        layer2_reports = reports.get("layer2", {})
        layer1_completed = len(completed_dims.get("layer1", [])) >= len(get_layer_dimensions(1))
        layer2_completed = len(completed_dims.get("layer2", [])) >= len(get_layer_dimensions(2))
        return bool(layer1_reports) and bool(layer2_reports) and layer1_completed and layer2_completed
    return True


def _build_initial_state(request: StartPlanningRequest, session_id: str) -> Dict[str, Any]:
    """
    Build initial state for main graph execution

    Delegates to PlanningService for actual state building.
    This wrapper maintains backward compatibility with existing code.

    Args:
        request: Planning request with user inputs
        session_id: Unique session identifier

    Returns:
        Complete initial state dictionary
    """
    logger.info(f"[Planning API] 构建 LangGraph 初始状态")
    logger.info(f"[Planning API] village_data 字段长度: {len(request.village_data)} 字符")

    # Delegate to planning_service
    return planning_service.build_initial_state(
        project_name=request.project_name,
        village_data=request.village_data,
        task_description=request.task_description,
        constraints=request.constraints,
        session_id=session_id,
        enable_review=request.enable_review,
        stream_mode=request.stream_mode,
        step_mode=request.step_mode,
    )


# ============================================
# Background Execution Function - 委托给 PlanningService
# ============================================

async def _execute_graph_in_background(
    session_id: str,
    graph,
    initial_state: Dict[str, Any],
    checkpointer
):
    """
    在后台执行 LangGraph 并将事件写入会话状态

    委托给 PlanningService.execute_graph_background 执行实际逻辑。
    """
    await planning_service.execute_graph_background(
        session_id=session_id,
        graph=graph,
        initial_state=initial_state,
        checkpointer=checkpointer,
        append_event_func=_append_session_event,
        append_event_async_func=_append_session_event_async,
    )


async def _resume_graph_execution(session_id: str, state: Dict[str, Any] = None) -> Dict[str, Any]:
    """
    Resume graph execution from checkpoint

    委托给 PlanningService.resume_from_checkpoint 执行实际逻辑。
    """
    from backend.database.operations_async import update_session_async as update_session

    saver = await get_global_checkpointer()
    graph = create_unified_planning_graph(checkpointer=saver)
    config = {"configurable": {"thread_id": session_id}}

    # 调用服务层方法
    result = await planning_service.resume_from_checkpoint(
        session_id=session_id,
        checkpointer=saver,
        append_event_func=_append_session_event,
        update_session_func=update_session,
        set_stream_state_func=_set_stream_state,
    )

    # 启动后台执行
    asyncio.create_task(
        _execute_graph_in_background(session_id, graph, None, saver)
    )

    return result


# ============================================
# API Endpoints
# ============================================

@router.post("/api/planning/start")
async def start_planning(
    request: StartPlanningRequest,
    background_tasks: BackgroundTasks,
    limiter: RateLimiterDep
):
    """
    Start a new planning session

    Creates a new session and initializes the main graph.
    Returns session_id immediately for SSE streaming.
    """
    start_time = time.time()

    try:
        logger.info(f"[Planning API] ===== 开始规划流程 =====")
        logger.info(f"[Planning API] 项目名称: {request.project_name}")
        logger.info(f"[Planning API] 村庄数据长度: {len(request.village_data)} 字符")
        logger.info(f"[Planning API] 任务描述: {request.task_description}")
        logger.info(f"[Planning API] 步进模式: {request.step_mode}")
        logger.info(f"[Planning API] 流式输出: {request.stream_mode}")

        # ===== Rate limit check =====
        allowed, message = limiter.check_rate_limit(
            project_name=request.project_name,
            session_id=""  # session_id not yet generated
        )

        if not allowed:
            logger.warning(f"[Planning API] 限流触发: {message}")

            # Calculate retry-after time if available
            retry_after = limiter.get_retry_after(request.project_name)

            raise HTTPException(
                status_code=429,  # 429 Too Many Requests
                detail=message,
                headers={"Retry-After": str(retry_after)} if retry_after is not None else {}
            )
        logger.info(f"[Planning API] 限流检查通过")
        # ===== Rate limit check end =====

        # Defensive check: Detect if village_data equals task_description
        if request.village_data == request.task_description:
            logger.warning(
                f"[Planning API] ⚠️ 警告：village_data 与 task_description 完全相同！"
                "这通常表明用户未上传文件"
            )

        # Validate input
        if not request.project_name or not request.project_name.strip():
            raise HTTPException(status_code=400, detail="项目名称不能为空")

        if not request.village_data or len(request.village_data.strip()) < 10:
            logger.error(f"[Planning API] 村庄数据验证失败: 长度={len(request.village_data) if request.village_data else 0}")
            raise HTTPException(status_code=400, detail="村庄数据不能为空或过短（至少需要10个字符）")

        session_id = _generate_session_id()
        logger.info(f"[Planning API] 生成会话ID: {session_id}")

        # Mark task as started
        limiter.mark_task_started(request.project_name)

        # Build initial state
        initial_state = _build_initial_state(request, session_id)
        logger.info(f"[Planning API] 初始状态构建完成")

        # Initialize session state for database creation
        session_state = {
            "session_id": session_id,
            "project_name": request.project_name,
            "status": TaskStatus.running,
            "created_at": datetime.now().isoformat(),
            "request": request.dict(),
            # ✅ 只存储业务元数据,不存储 AI 生成的字段
        }

        # ✅ P0 FIX: Create database session FIRST before returning response
        # This prevents 404 errors when frontend polls immediately after receiving task_id
        db_start_time = time.time()
        try:
            logger.info(f"[Planning API] [{session_id}] Creating database session...")
            logger.debug(f"[Planning API] [{session_id}] Session state: project={request.project_name}, step_mode={request.step_mode}")

            await create_session_async(session_state)

            db_elapsed = (time.time() - db_start_time) * 1000
            logger.info(f"[Planning API] [{session_id}] ✓ Database session created successfully ({db_elapsed:.2f}ms)")
            logger.info(f"[Planning API] [{session_id}] Frontend can now safely poll /api/planning/status/{session_id}")
        except Exception as db_error:
            db_elapsed = (time.time() - db_start_time) * 1000
            logger.error(
                f"[Planning API] [{session_id}] ✗ Database session creation failed after {db_elapsed:.2f}ms: {db_error}",
                exc_info=True
            )
            logger.warning(f"[Planning API] [{session_id}] Cleaning up rate limiter state for project: {request.project_name}")

            # Clean up in-memory state
            limiter.mark_task_completed(request.project_name, success=False)

            raise HTTPException(
                status_code=500,
                detail=f"Failed to create planning session in database: {str(db_error)}"
            )

        # Initialize in-memory session with events list (after DB commit)
        # SSOT: Only keep SSE-required minimal fields via SSEManager
        sse_manager.init_session(session_id, {
            "session_id": session_id,
            "project_name": request.project_name,
            "created_at": datetime.now().isoformat(),
            "events": deque(maxlen=MAX_SESSION_EVENTS),  # SSE event queue
        })

        # Mark execution as active (数据库写入)
        await _set_execution_active(session_id, True)

        # 使用全局 checkpointer 单例
        saver = await get_global_checkpointer()

        logger.info(f"[Planning API] 创建 LangGraph 实例 (使用全局 AsyncSqliteSaver)")
        graph = create_unified_planning_graph(checkpointer=saver)
        
        # Start background execution (non-blocking)
        # ✅ At this point, the database record already exists, so frontend polling will succeed
        background_tasks.add_task(
            _execute_graph_in_background,
            session_id,
            graph,
            initial_state,
            saver
        )
        logger.info(f"[Planning API] [{session_id}] Background task submitted")

        elapsed = (time.time() - start_time) * 1000
        logger.info(f"[Planning API] [{session_id}] ✓ Session started successfully - returning response ({elapsed:.2f}ms)")
        logger.info(f"[Planning API] [{session_id}] Response: task_id={session_id}, status=running, stream_url=/api/planning/stream/{session_id}")

        return {
            "task_id": session_id,
            "status": TaskStatus.running,
            "message": "Planning session started",
            "stream_url": f"/api/planning/stream/{session_id}"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[Planning API] Failed to start planning: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to start planning: {str(e)}")


@router.get("/api/planning/stream/{session_id}")
async def stream_planning(session_id: str):
    # 1. Memory miss -> try rebuild from database
    if not sse_manager.session_exists(session_id):
        rebuilt = await _rebuild_session_from_db(session_id)
        if not rebuilt:
            raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    # SSE connection logging
    session_state = sse_manager.get_session(session_id) or {}
    current_layer = session_state.get("current_layer", "?")
    sent_layer_events = session_state.get("sent_layer_events", set())
    stream_state = sse_manager.get_stream_state(session_id)
    subscriber_count_before = sse_manager.get_subscriber_count(session_id)
    
    logger.info(f"[Planning API] [{session_id}] ===== SSE 连接建立 =====")
    logger.info(f"[Planning API] [{session_id}] 连接前状态: current_layer={current_layer}, stream_state={stream_state}")
    logger.info(f"[Planning API] [{session_id}] 已发送的层级事件: {sent_layer_events}")
    logger.info(f"[Planning API] [{session_id}] 连接前订阅者数量: {subscriber_count_before}")

    async def event_generator():
        # 🔧 订阅 session 的 asyncio.Queue（事件驱动模式）
        queue = await subscribe_session(session_id)
        
        try:
            # 立即发送连接成功事件
            yield sse_manager.format_sse({
                "type": "connected",
                "session_id": session_id,
                "timestamp": datetime.now().isoformat()
            })

            while True:
                try:
                    # 🔧 事件驱动：等待事件到达，无需轮询！
                    event = await asyncio.wait_for(
                        queue.get(),
                        timeout=30.0  # 30秒超时，发送 keep-alive
                    )
                    
                    event_type = event.get("type")
                    
                    # 打印发送详情
                    if event_type == "dimension_delta":
                        dim_key = event.get("dimension_key", "?")
                        accumulated_len = len(event.get("accumulated", ""))
                        logger.debug(f"[Planning] [{session_id}] SSE发送: {event_type} [{dim_key}] accumulated={accumulated_len}")
                    elif event_type == "dimension_complete":
                        # 🔧 新增：dimension_complete 事件日志
                        dim_key = event.get("dimension_key", "?")
                        layer = event.get("layer", "?")
                        content_len = len(event.get("full_content", ""))
                        logger.info(f"[Planning] [{session_id}] SSE发送: {event_type} layer={layer}, dimension={dim_key}, chars={content_len}")
                    elif event_type == "layer_completed":
                        layer = event.get("layer", "?")
                        dim_count = event.get("dimension_count", 0)
                        total_chars = event.get("total_chars", 0)
                        logger.info(f"[Planning] [{session_id}] SSE发送: {event_type} layer={layer}, dims={dim_count}, chars={total_chars}")
                    elif event_type == "layer_started":
                        layer = event.get("layer", "?")
                        layer_name = event.get("layer_name", "?")
                        logger.info(f"[Planning] [{session_id}] SSE发送: {event_type} layer={layer} ({layer_name})")
                    else:
                        logger.info(f"[Planning] [{session_id}] SSE发送: {event_type}")

                    # 发送事件
                    yield sse_manager.format_sse(event)

                    # 检查终止事件
                    if event_type in ["completed", "error"]:
                        logger.info(f"[Planning] [{session_id}] SSE 流结束: {event_type}")
                        return
                    elif event_type == "stream_paused":
                        sse_manager.set_stream_state(session_id, "paused")
                        logger.info(f"[Planning] [{session_id}] stream_paused: 发送并关闭连接")
                        return
                        
                except asyncio.TimeoutError:
                    # 30秒无事件，发送心跳保持连接
                    yield ": keep-alive\n\n"

        except asyncio.CancelledError:
            subscriber_count_after = sse_manager.get_subscriber_count(session_id)
            logger.info(f"[Planning] [{session_id}] SSE 连接已关闭（Cancelled），剩余订阅者: {subscriber_count_after}")
        except Exception as e:
            logger.error(f"[Planning] SSE error for {session_id}: {e}", exc_info=True)
            yield sse_manager.format_sse({
                "type": "error",
                "session_id": session_id,
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            })
        finally:
            # 🔧 取消订阅
            final_subscriber_count = sse_manager.get_subscriber_count(session_id)
            logger.info(f"[Planning] [{session_id}] SSE finally: 取消订阅，当前订阅者数: {final_subscriber_count}")
            await sse_manager.unsubscribe(session_id, queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


@router.get("/api/planning/status/{session_id}")
async def get_session_status(session_id: str):
    """
    Get session status
    
    ✅ SSOT 简化：只从 LangGraph Checkpoint 读取状态，不再从内存 _sessions 读取
    - Checkpoint 是唯一真实源
    - 数据库只用于业务元数据（status, created_at, execution_error）
    
    Args:
        session_id: Session identifier

    Returns:
        SessionStatusResponse with current state
    """
    # 1. 从数据库获取业务元数据
    db_session = await get_session_async(session_id)
    if not db_session:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    # 2. 从 LangGraph Checkpoint 获取完整状态 - NEW Schema
    phase = "init"
    current_wave = 1
    reports = {"layer1": {}, "layer2": {}, "layer3": {}}
    completed_dimensions = {"layer1": [], "layer2": [], "layer3": []}
    pause_after_step = False
    messages = []
    revision_history = []
    metadata = {}
    version = 0
    
    try:
        checkpointer = await get_global_checkpointer()
        graph = create_unified_planning_graph(checkpointer=checkpointer)
        config = {"configurable": {"thread_id": session_id}}
        checkpoint_state = await graph.aget_state(config)
        
        if checkpoint_state and checkpoint_state.values:
            state = checkpoint_state.values

            # Read from NEW UnifiedPlanningState Schema
            phase = state.get("phase", "init")
            current_wave = state.get("current_wave", 1)
            reports = state.get("reports", {"layer1": {}, "layer2": {}, "layer3": {}})
            completed_dimensions = state.get("completed_dimensions", {"layer1": [], "layer2": [], "layer3": []})
            pause_after_step = state.get("pause_after_step", False)

            # Extract messages
            raw_messages = state.get("messages", [])
            for msg in raw_messages:
                if hasattr(msg, 'content'):
                    messages.append({
                        "type": msg.__class__.__name__.lower().replace("message", ""),
                        "content": msg.content,
                        "role": "assistant" if "ai" in msg.__class__.__name__.lower() else "user"
                    })

            revision_history = state.get("revision_history", [])

            # Metadata
            metadata = state.get("metadata", {})
            version = metadata.get("version", 0)

            logger.debug(f"[Status] [{session_id}] Checkpoint: phase={phase}, wave={current_wave}, version={version}")
    except Exception as e:
        logger.warning(f"[Status] [{session_id}] 获取 Checkpoint 失败: {e}")

    # 3. 计算进度 - based on NEW phase field
    phase_order = ["init", "layer1", "layer2", "layer3", "completed"]
    try:
        phase_idx = phase_order.index(phase)
        current_layer = phase_idx  # Map phase to layer number
    except ValueError:
        current_layer = 1

    progress = None
    if phase == "completed":
        progress = 100
    elif phase.startswith("layer"):
        layer_num = int(phase.replace("layer", ""))
        progress = (layer_num / 3) * 100

    # Check layer completion from NEW completed_dimensions
    layer_1_completed = len(completed_dimensions.get("layer1", [])) >= len(get_layer_dimensions(1))
    layer_2_completed = len(completed_dimensions.get("layer2", [])) >= len(get_layer_dimensions(2))
    layer_3_completed = len(completed_dimensions.get("layer3", [])) >= len(get_layer_dimensions(3))

    # Overall execution complete status
    execution_complete = layer_1_completed and layer_2_completed and layer_3_completed

    # Get checkpoint_id from config
    last_checkpoint_id = checkpoint_state.config.get("configurable", {}).get("checkpoint_id", "") if checkpoint_state else ""

    # Extract reports for legacy compatibility
    analysis_reports = reports.get("layer1", {})
    concept_reports = reports.get("layer2", {})
    detail_reports = reports.get("layer3", {})

    return {
        "session_id": session_id,
        # Business metadata (from DB)
        "status": db_session.get("status", "running"),
        "execution_error": db_session.get("execution_error"),
        "created_at": db_session.get("created_at", ""),
        # Version for frontend sync
        "version": version,
        # NEW Schema fields
        "phase": phase,
        "current_wave": current_wave,
        "reports": reports,
        "completed_dimensions": completed_dimensions,
        # Legacy fields (for frontend compatibility during Phase 1)
        "current_layer": current_layer,
        "layer_1_completed": layer_1_completed,
        "layer_2_completed": layer_2_completed,
        "layer_3_completed": layer_3_completed,
        "pause_after_step": pause_after_step,
        "execution_complete": execution_complete,
        "progress": progress,
        "last_checkpoint_id": last_checkpoint_id,
        # Messages and revision history
        "messages": messages,
        "revision_history": revision_history,
        # UI messages
        "ui_messages": await get_ui_messages_async(session_id),
        # Reports (legacy format)
        "analysis_reports": analysis_reports,
        "concept_reports": concept_reports,
        "detail_reports": detail_reports,
    }


# ============================================
# Signal-Fetch Pattern: REST API 获取层级报告
# ============================================

@router.get("/api/planning/sessions/{session_id}/layer/{layer}/reports")
async def get_layer_reports(session_id: str, layer: int):
    """
    Signal-Fetch Pattern: Get layer reports from Checkpoint

    Frontend calls this API after receiving SSE layer_completed signal
    to fetch complete, reliable dimension reports.

    Args:
        session_id: Session ID
        layer: Layer number (1/2/3)

    Returns:
        Layer reports with completion status
    """
    from backend.services.session_service import session_service
    from backend.services.checkpoint_service import checkpoint_service

    # Validate layer
    if layer not in [1, 2, 3]:
        raise HTTPException(status_code=400, detail=f"Invalid layer: {layer}. Must be 1, 2, or 3.")

    # Validate session exists
    db_session = await get_session_async(session_id)
    if not db_session:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    try:
        # Delegate to session_service
        response = await session_service.get_layer_reports(session_id, layer)

        # Get project name from checkpoint
        project_name = await checkpoint_service.get_project_name(session_id)

        return {
            "layer": response.layer,
            "reports": response.reports,
            "report_content": "",  # Report generation removed
            "project_name": project_name,
            "completed": response.completed,
            "stats": response.stats,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[Planning API] [{session_id}] Failed to get layer {layer} reports: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get layer reports: {str(e)}")


@router.post("/api/planning/messages/{session_id}")
async def create_ui_message(session_id: str, request: CreateUIMessageRequest):
    """
    存储 UI 消息到数据库（使用 Upsert）
    
    根据 (session_id, message_id) 唯一约束自动判断是更新还是创建。
    
    Args:
        session_id: Session identifier
        request: Message data (包含前端消息 ID)
        
    Returns:
        Created/updated message database ID
    """
    # 验证 session 存在
    db_session = await get_session_async(session_id)
    if not db_session:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")
    
    try:
        # ✅ 使用 upsert 替代 create
        db_id = await upsert_ui_message_async(
            session_id=session_id,
            message_id=request.message_id,  # 前端消息 ID
            role=request.role,
            content=request.content,
            message_type=request.message_type,
            metadata=request.metadata
        )
        return {"success": True, "message_id": db_id, "frontend_id": request.message_id}
    except Exception as e:
        logger.error(f"[Planning API] Failed to upsert UI message: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to upsert message: {str(e)}")


@router.get("/api/planning/messages/{session_id}")
async def get_ui_messages(session_id: str, role: Optional[str] = None, limit: int = 100):
    """
    获取会话的 UI 消息列表
    
    Args:
        session_id: Session identifier
        role: Filter by role (optional)
        limit: Maximum number of messages
        
    Returns:
        List of UI messages
    """
    # 验证 session 存在
    db_session = await get_session_async(session_id)
    if not db_session:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")
    
    messages = await get_ui_messages_async(session_id, role=role, limit=limit)
    return {"success": True, "messages": messages}


@router.post("/api/planning/chat/{session_id}")
async def send_chat_message(session_id: str, request: ChatMessageRequest):
    """
    发送对话消息到规划会话

    通过 LangGraph stream 模式处理 conversation_node，支持：
    - 普通对话（问答）
    - 工具调用
    - 推进规划（触发 AdvancePlanningIntent）

    SSE 会推送以下事件：
    - ai_response_delta: AI 响应增量
    - ai_response_complete: AI 响应完成
    - tool_call/tool_progress/tool_result: 工具执行事件
    - dimension_delta/dimension_complete: 规划维度生成事件

    Args:
        session_id: Session identifier
        request: Chat message content

    Returns:
        Status indicating message was processed
    """
    logger.info(f"[Planning API] [{session_id}] 收到对话消息: {request.message[:50]}...")

    # 验证 session 存在
    db_session = await get_session_async(session_id)
    if not db_session:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    # 获取 checkpointer 和图实例
    checkpointer = await get_global_checkpointer()
    graph = create_unified_planning_graph(checkpointer=checkpointer)

    config = {"configurable": {"thread_id": session_id}}

    # 添加用户消息到状态
    user_message = HumanMessage(content=request.message)

    # 使用 stream 模式执行，发送增量事件
    # 使用 list 收集 tokens，避免 O(n) 字符串拼接
    content_chunks: List[str] = []

    try:
        async for event in graph.astream_events(
            {"messages": [user_message]},
            config=config,
            version="v2"
        ):
            event_type = event.get("event")
            data = event.get("data", {})

            # 处理 AI 响应增量
            if event_type == "on_chain_stream":
                chunk = data.get("chunk")
                if chunk and hasattr(chunk, "content"):
                    token = chunk.content
                    content_chunks.append(token)
                    accumulated_content = "".join(content_chunks)

                    # 发送增量事件
                    _append_session_event(session_id, {
                        "type": "ai_response_delta",
                        "delta": token,
                        "accumulated": accumulated_content,
                        "timestamp": datetime.now().isoformat()
                    })

            # 处理工具调用事件
            elif event_type == "on_tool_start":
                tool_name = data.get("name", "unknown")
                _append_session_event(session_id, {
                    "type": "tool_call",
                    "tool_name": tool_name,
                    "timestamp": datetime.now().isoformat()
                })

            elif event_type == "on_tool_end":
                tool_name = data.get("name", "unknown")
                output = data.get("output", "")
                _append_session_event(session_id, {
                    "type": "tool_result",
                    "tool_name": tool_name,
                    "status": "success",
                    "result_preview": str(output)[:200] if output else "",
                    "timestamp": datetime.now().isoformat()
                })

        # 发送响应完成事件
        final_content = "".join(content_chunks)
        _append_session_event(session_id, {
            "type": "ai_response_complete",
            "content": final_content,
            "timestamp": datetime.now().isoformat()
        })

        logger.info(f"[Planning API] [{session_id}] 对话消息处理完成")

        return {
            "success": True,
            "session_id": session_id,
            "message": "Chat message processed"
        }

    except Exception as e:
        logger.error(f"[Planning API] [{session_id}] 对话消息处理失败: {e}", exc_info=True)
        _append_session_event(session_id, {
            "type": "error",
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        })
        raise HTTPException(status_code=500, detail=f"Chat processing failed: {str(e)}")


@router.post("/api/planning/review/{session_id}")
async def review_action(session_id: str, request: ReviewActionRequest):
    """
    Handle review actions from web frontend

    Delegates to ReviewService for business logic.
    """
    from backend.services.review_service import review_service

    logger.info(f"[Planning API] review_action called: session_id={session_id}, action={request.action}")

    try:
        # Get session from memory or rebuild from database
        session = sse_manager.get_session(session_id)
        if not session:
            session = await _rebuild_session_from_db(session_id)
            if not session:
                raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

        # Get current state from checkpoint
        checkpointer = await get_global_checkpointer()
        graph = create_unified_planning_graph(checkpointer=checkpointer)
        config = {"configurable": {"thread_id": session_id}}

        checkpoint_state = await graph.aget_state(config)
        if not checkpoint_state or not checkpoint_state.values:
            raise HTTPException(status_code=404, detail=f"Session not found in checkpoint: {session_id}")

        state = checkpoint_state.values
        review_id = state.get("review_id", "")
        is_pause_mode = state.get("pause_after_step", False)

        # Validate that there's a pending review
        if not review_id and not is_pause_mode and request.action != "rollback":
            raise HTTPException(status_code=400, detail="No pending review or pause")

        # ---------- approve ----------
        if request.action == "approve":
            response = await review_service.approve(session_id, review_id)

            # Resume execution in background
            asyncio.create_task(_resume_graph_execution(session_id))

            return response.to_dict()

        # ---------- reject ----------
        elif request.action == "reject":
            response = await review_service.reject(
                session_id,
                request.feedback or "",
                request.dimensions,
                review_id,
            )

            # Resume execution in background
            asyncio.create_task(_resume_graph_execution(session_id))

            return response.to_dict()

        # ---------- rollback ----------
        elif request.action == "rollback":
            if not request.checkpoint_id:
                raise HTTPException(status_code=400, detail="Checkpoint ID required for rollback")

            response = await review_service.rollback(
                session_id,
                request.checkpoint_id,
                review_id,
            )

            return response.to_dict()

        else:
            raise HTTPException(status_code=400, detail=f"Unknown action: {request.action}")

    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"[Planning API] Review action error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Review action failed: {str(e)}")

@router.delete("/api/planning/sessions/{session_id}")
async def delete_session(session_id: str):
    """
    Delete a session completely

    Delegates to SessionService for complete session removal.
    """
    from backend.services.session_service import session_service

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
    Resume execution from checkpoint

    Loads checkpoint state from LangGraph and creates new session for continued execution.
    """
    try:
        session_id = _generate_session_id()
        logger.info(f"[Planning API] Resuming from checkpoint {request.checkpoint_id}")

        # 使用 LangGraph API 获取检查点状态
        checkpointer = await get_global_checkpointer()
        graph = create_unified_planning_graph(checkpointer=checkpointer)

        # 从原始 session 的 thread_id 获取状态（需要前端传入原始 session_id）
        # 注意：这里需要原始 session_id 来正确获取 checkpoint
        # 暂时使用 project_name 作为 thread_id（需要改进）
        config = {"configurable": {"thread_id": request.project_name}}

        # 查找目标检查点
        target_state = None
        async for state_snapshot in graph.aget_state_history(config):
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

        # SSOT: Initialize SSE-required minimal fields via SSEManager
        sse_manager.init_session(session_id, {
            "session_id": session_id,
            "project_name": request.project_name,
            "created_at": datetime.now().isoformat(),
            "events": deque(maxlen=MAX_SESSION_EVENTS),  # SSE event queue
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


@router.get("/api/planning/checkpoints/{project_name}")
async def list_checkpoints(project_name: str, session_id: Optional[str] = None):
    """
    List all checkpoints for a project from LangGraph

    Args:
        project_name: 项目名称
        session_id: 会话 ID（推荐传入，确保与 rollback 使用相同的 thread_id）
    """
    try:
        checkpointer = await get_global_checkpointer()
        graph = create_unified_planning_graph(checkpointer=checkpointer)

        # 使用 session_id 作为 thread_id（与 rollback 保持一致）
        # 如果没有 session_id，回退功能将无法使用
        thread_id = session_id or project_name
        config = {"configurable": {"thread_id": thread_id}}
        
        logger.info(f"[Checkpoints] list_checkpoints: project_name={project_name}, session_id={session_id}, thread_id={thread_id}")

        checkpoints = []
        async for state_snapshot in graph.aget_state_history(config):
            checkpoint_id = state_snapshot.config.get("configurable", {}).get("checkpoint_id", "")
            
            # 跳过空 checkpoint_id
            if not checkpoint_id:
                continue
            
            values = state_snapshot.values or {}

            # ✅ 修复时间戳格式：确保返回 ISO 8601 格式
            raw_timestamp = ""
            if state_snapshot.metadata:
                # LangGraph 的 write_ts 可能是 Unix 时间戳或其他格式
                raw_timestamp = state_snapshot.metadata.get("write_ts", "")
            
            # 尝试转换为 ISO 格式
            timestamp = ""
            if raw_timestamp:
                try:
                    # 如果是 Unix 时间戳（整数或浮点数）
                    if isinstance(raw_timestamp, (int, float)):
                        from datetime import datetime, timezone
                        dt = datetime.fromtimestamp(raw_timestamp, tz=timezone.utc)
                        timestamp = dt.isoformat()
                    # 如果已经是字符串，尝试解析并重新格式化
                    elif isinstance(raw_timestamp, str):
                        # 尝试多种格式解析
                        parsed = None
                        for fmt in ["%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"]:
                            try:
                                parsed = datetime.strptime(raw_timestamp, fmt)
                                break
                            except ValueError:
                                continue
                        if parsed:
                            timestamp = parsed.isoformat()
                        else:
                            # 尝试作为 Unix 时间戳解析
                            try:
                                ts = float(raw_timestamp)
                                from datetime import timezone
                                dt = datetime.fromtimestamp(ts, tz=timezone.utc)
                                timestamp = dt.isoformat()
                            except ValueError:
                                timestamp = raw_timestamp  # 保持原样
                except Exception as e:
                    logger.warning(f"[Checkpoints] Failed to parse timestamp {raw_timestamp}: {e}")
                    timestamp = str(raw_timestamp)
            
            # 如果没有有效时间戳，使用当前时间
            if not timestamp:
                timestamp = datetime.now().isoformat()

            # 构建检查点信息
            # 优先从 metadata 读取检查点类型和阶段
            state_metadata = values.get("metadata", {})
            checkpoint_type = state_metadata.get("checkpoint_type", "regular")
            checkpoint_phase = state_metadata.get("checkpoint_phase", "")
            checkpoint_description = state_metadata.get("checkpoint_description", "")
            
            # 从 phase 字段读取（新增的明确阶段标识）
            phase = values.get("phase", checkpoint_phase)
            
            # 确定层级和描述
            completed_layer = values.get("previous_layer", 0)
            current_layer = values.get("current_layer", 1)
            
            # 根据类型确定描述
            if checkpoint_type == "key" and checkpoint_description:
                description = checkpoint_description
                display_layer = state_metadata.get("checkpoint_layer", completed_layer)
            elif completed_layer > 0:
                # Layer N 刚完成的状态
                description = f"Layer {completed_layer} 完成"
                display_layer = completed_layer
            else:
                # 初始状态
                description = "初始状态"
                display_layer = 0
            
            checkpoint_info = {
                "checkpoint_id": checkpoint_id,
                "timestamp": timestamp,
                "type": checkpoint_type,  # 新增：检查点类型 (key/regular)
                "phase": phase,           # 新增：规划阶段
                "layer": display_layer,
                "current_layer": current_layer,
                "previous_layer": completed_layer,
                "description": description,
            }
            checkpoints.append(checkpoint_info)

        return {
            "project_name": project_name,
            "checkpoints": checkpoints,
            "count": len(checkpoints)
        }

    except Exception as e:
        logger.error(f"[Planning API] List checkpoints error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to list checkpoints: {str(e)}")

async def _rebuild_session_from_db(session_id: str) -> Optional[Dict[str, Any]]:
    """
    从数据库 + Checkpoint 完整重建内存会话
    
    ✅ SSOT 模式：从 LangGraph Checkpoint 获取完整状态，确保 review_action 等操作能正常工作
    """
    db_session = await get_session_async(session_id)
    if not db_session:
        return None

    # ✅ 从 Checkpoint 获取完整状态
    initial_state = {}
    try:
        checkpointer = await get_global_checkpointer()
        if checkpointer:
            graph = create_unified_planning_graph(checkpointer=checkpointer)
            config = {"configurable": {"thread_id": session_id}}
            checkpoint_state = await graph.aget_state(config)
            if checkpoint_state and checkpoint_state.values:
                initial_state = dict(checkpoint_state.values)
                logger.info(f"[Planning API] [{session_id}] 从 Checkpoint 恢复状态成功")
    except Exception as e:
        logger.warning(f"[Planning API] [{session_id}] Checkpoint 读取失败: {e}")

    # Initialize memory session via SSEManager
    session_data = {
        "session_id": db_session["session_id"],
        "project_name": db_session["project_name"],
        "created_at": db_session["created_at"].isoformat() if isinstance(db_session["created_at"], datetime) else db_session["created_at"],
        "events": deque(maxlen=MAX_SESSION_EVENTS),  # SSE event queue
        "initial_state": initial_state,  # Full state from checkpoint
    }
    sse_manager.init_session(session_id, session_data)

    logger.info(f"[Planning API] [{session_id}] Memory session rebuilt from database (with initial_state)")
    return session_data


@router.get("/api/planning/rate-limit/status")
async def get_rate_limit_status(limiter: RateLimiterDep):
    """Get rate limit status (for monitoring)"""
    return limiter.get_status()


@router.post("/api/planning/rate-limit/reset/{project_name}")
async def reset_rate_limit(project_name: str, limiter: RateLimiterDep):
    """Reset rate limit status for a project (admin function)"""
    success = limiter.reset_project(project_name)
    if success:
        return {"message": f"已重置项目 '{project_name}' 的限流状态"}
    else:
        raise HTTPException(status_code=404, detail=f"项目不存在: {project_name}")


# ============================================
# Dimension Content & Revision History APIs
# ============================================

@router.get("/api/planning/sessions/{session_id}/dimensions/{dimension_key}")
async def get_dimension_content(session_id: str, dimension_key: str):
    """
    【Signal-Fetch Pattern】从 Checkpoint 获取单个维度的最新内容
    
    当前端收到 dimension_revised SSE 信号后，调用此 API 获取完整内容。
    
    Args:
        session_id: 会话 ID
        dimension_key: 维度标识（如 "village_overview", "population_scale"）
        
    Returns:
        {
            "dimension_key": "village_overview",
            "layer": 1,
            "content": "...",
            "previous_content": "...",  # 上一个版本的内容（用于显示修复前后对比）
            "version": 2,
            "exists": true,
            "has_previous": true
        }
    """
    from src.config.dimension_metadata import get_dimension_layer
    
    # 验证 session 存在
    db_session = await get_session_async(session_id)
    if not db_session:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")
    
    try:
        # 从 Checkpoint 获取完整状态
        checkpointer = await get_global_checkpointer()
        graph = create_unified_planning_graph(checkpointer=checkpointer)
        config = {"configurable": {"thread_id": session_id}}
        checkpoint_state = await graph.aget_state(config)
        
        if not checkpoint_state or not checkpoint_state.values:
            raise HTTPException(status_code=404, detail=f"No checkpoint found for session: {session_id}")
        
        # 获取维度所在层级
        layer = get_dimension_layer(dimension_key)
        if not layer:
            raise HTTPException(status_code=400, detail=f"Unknown dimension: {dimension_key}")
        
        # Get reports from NEW Schema
        reports_dict = checkpoint_state.values.get("reports", {})
        layer_key = f"layer{layer}"
        reports = reports_dict.get(layer_key, {})
        
        content = reports.get(dimension_key, "")
        
        # 获取版本号和上一个版本内容（从修订历史）
        from backend.database.operations_async import (
            get_latest_dimension_version_async,
            get_previous_dimension_version_async
        )
        latest_version = await get_latest_dimension_version_async(session_id, layer, dimension_key)
        version = latest_version.get("version", 1) if latest_version else 1
        
        # ✅ 获取上一个版本的内容（用于前端显示修复前后对比）
        previous_content = None
        if version > 1:
            previous_revision = await get_previous_dimension_version_async(
                session_id, layer, dimension_key, version
            )
            if previous_revision:
                previous_content = previous_revision.get("content")
        
        return {
            "dimension_key": dimension_key,
            "layer": layer,
            "content": content,
            "previous_content": previous_content,
            "version": version,
            "exists": bool(content),
            "has_previous": previous_content is not None,
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[Planning API] Failed to get dimension content: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/planning/sessions/{session_id}/dimensions/{dimension_key}/revisions")
async def get_dimension_revisions(session_id: str, dimension_key: str, limit: int = 20):
    """
    获取维度的修订历史
    
    Args:
        session_id: 会话 ID
        dimension_key: 维度标识
        limit: 最大返回数量
        
    Returns:
        {
            "dimension_key": "village_overview",
            "revisions": [...]
        }
    """
    from ..config.dimension_metadata import get_dimension_layer
    
    # 验证 session 存在
    db_session = await get_session_async(session_id)
    if not db_session:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")
    
    # 获取维度所在层级
    layer = get_dimension_layer(dimension_key)
    if not layer:
        raise HTTPException(status_code=400, detail=f"Unknown dimension: {dimension_key}")
    
    # 查询修订历史
    from backend.database.operations_async import get_dimension_revisions_async
    revisions = await get_dimension_revisions_async(
        session_id=session_id,
        layer=layer,
        dimension_key=dimension_key,
        limit=limit,
    )
    
    return {
        "dimension_key": dimension_key,
        "layer": layer,
        "revisions": revisions,
        "count": len(revisions),
    }


__all__ = ["router"]
