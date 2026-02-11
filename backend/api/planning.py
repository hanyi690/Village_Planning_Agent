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
"""

import asyncio
import json
import logging
import sys
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Any, Dict, Generator, List, Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from backend.api.tool_manager import tool_manager
from backend.schemas import TaskStatus
from backend.services.rate_limiter import rate_limiter
from backend.utils.progress_helper import calculate_progress
from backend.utils.logging import _extract_session_id
from backend.database import (
    create_planning_session,
    get_planning_session,
    update_planning_session,
    delete_planning_session,
    update_session_state,
    add_session_event,
    get_session_events,
)
from backend.database.operations_enhanced import (
    update_session_state_safe,
    update_session_layer_completion,
)
from src.orchestration.main_graph import create_village_planning_graph
from src.utils.output_manager import create_output_manager
from src.utils.paths import get_results_dir

router = APIRouter()
logger = logging.getLogger(__name__)

# In-memory session storage (for production: use Redis)
# NOTE: This is now backed by database, but we keep in-memory cache for performance
_sessions: Dict[str, Dict[str, Any]] = {}
# Track active executions to prevent duplicate runs
_active_executions: Dict[str, bool] = {}
# Store checkpointers for resume operations (keyed by session_id)
_session_checkpointer: Dict[str, Any] = {}
# Track stream states to prevent infinite reconnection
_stream_states: Dict[str, str] = {}  # session_id -> "active" | "paused" | "completed"

# Thread safety locks
_sessions_lock = Lock()
_active_executions_lock = Lock()
_stream_states_lock = Lock()


# ============================================
# Thread-Safe Context Managers
# ============================================

@contextmanager
def _with_session_lock(session_id: str) -> Generator[Dict[str, Any], None, None]:
    """
    Thread-safe session access context manager.

    Args:
        session_id: Session identifier

    Yields:
        Session data dictionary

    Raises:
        HTTPException: If session not found
    """
    with _sessions_lock:
        if session_id not in _sessions:
            raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")
        yield _sessions[session_id]


def _get_session_copy(session_id: str) -> Optional[Dict[str, Any]]:
    """
    Get a thread-safe copy of session data.

    Args:
        session_id: Session identifier

    Returns:
        Copy of session data or None if not found
    """
    with _sessions_lock:
        if session_id not in _sessions:
            return None
        return _sessions[session_id].copy()


def _set_session_value(session_id: str, key: str, value: Any) -> bool:
    """
    Thread-safe session value update.

    Args:
        session_id: Session identifier
        key: Session key to update
        value: New value

    Returns:
        True if successful, False if session not found
    """
    with _sessions_lock:
        if session_id not in _sessions:
            return False
        _sessions[session_id][key] = value
        return True


def _is_execution_active(session_id: str) -> bool:
    """
    Thread-safe check if execution is active.

    Args:
        session_id: Session identifier

    Returns:
        True if execution is active
    """
    with _active_executions_lock:
        return _active_executions.get(session_id, False)


def _set_execution_active(session_id: str, active: bool) -> None:
    """
    Thread-safe set execution active state.

    Args:
        session_id: Session identifier
        active: Active state
    """
    with _active_executions_lock:
        _active_executions[session_id] = active


def _get_stream_state(session_id: str) -> str:
    """
    Thread-safe get stream state.

    Args:
        session_id: Session identifier

    Returns:
        Stream state: "active", "paused", or "completed"
    """
    with _stream_states_lock:
        return _stream_states.get(session_id, "active")


def _set_stream_state(session_id: str, state: str) -> None:
    """
    Thread-safe set stream state.

    Args:
        session_id: Session identifier
        state: New stream state
    """
    with _stream_states_lock:
        _stream_states[session_id] = state

# Flag to enable/disable database persistence
USE_DATABASE_PERSISTENCE = True  # Set to False to use in-memory only


# ============================================
# Request/Response Schemas
# ============================================

class StartPlanningRequest(BaseModel):
    """Request to start planning session"""
    project_name: str = Field(..., description="项目名称/村庄名称")
    village_data: str = Field(..., description="村庄现状数据")
    task_description: str = Field(default="制定村庄总体规划方案", description="规划任务描述")
    constraints: str = Field(default="无特殊约束", description="规划约束条件")
    enable_review: bool = Field(default=True, description="启用人工审查")
    step_mode: bool = Field(default=True, description="步进模式（每层暂停）")
    stream_mode: bool = Field(default=False, description="启用流式输出（token级实时传输）")


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


class SessionStatusResponse(BaseModel):
    """Session status response"""
    session_id: str
    status: str
    current_layer: Optional[int] = None
    created_at: str
    checkpoints: List[Dict[str, Any]]
    checkpoint_count: int
    progress: Optional[float] = None

    # Layer completion states
    layer_1_completed: bool = False
    layer_2_completed: bool = False
    layer_3_completed: bool = False

    # Pause/review states
    pause_after_step: bool = False
    waiting_for_review: bool = False
    last_checkpoint_id: Optional[str] = None

    # Error and completion states
    execution_error: Optional[str] = None
    execution_complete: bool = False

    # Timestamp
    updated_at: str


# ============================================
# Helper Functions
# ============================================

def _generate_session_id() -> str:
    """Generate session ID (timestamp format)"""
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _get_session_path(project_name: str, session_id: str) -> Path:
    """Get file system path for session"""
    safe_name = project_name.replace('/', '_').replace('\\', '_').replace(':', '_')
    return get_results_dir() / safe_name / session_id


def _sync_session_to_db(session_id: str) -> bool:
    """
    Sync session from in-memory to database
    将会话从内存同步到数据库

    Args:
        session_id: Session ID

    Returns:
        bool: True if successful
    """
    if not USE_DATABASE_PERSISTENCE:
        return True  # Skip if DB persistence disabled

    try:
        if session_id not in _sessions:
            return False

        session_data = _sessions[session_id]

        # Build state snapshot
        state = session_data.get("initial_state", {})
        state["current_layer"] = session_data.get("current_layer", 1)
        state["status"] = session_data.get("status", "running")

        # Update database
        update_session_state(session_id, state)

        return True

    except Exception as e:
        logger.error(f"Failed to sync session to DB: {e}", exc_info=True)
        return False


def _load_session_from_db(session_id: str) -> Optional[Dict[str, Any]]:
    """
    Load session from database to memory
    从数据库加载会话到内存

    Args:
        session_id: Session ID

    Returns:
        Session data or None
    """
    if not USE_DATABASE_PERSISTENCE:
        return None  # Skip if DB persistence disabled

    try:
        session_data = get_planning_session(session_id)

        if not session_data:
            return None

        # Convert to in-memory format
        return {
            "session_id": session_data["session_id"],
            "project_name": session_data["project_name"],
            "status": session_data["status"],
            "created_at": session_data["created_at"],
            "updated_at": session_data.get("updated_at", session_data["created_at"]),
            "current_layer": session_data["current_layer"],
            "initial_state": session_data.get("state_snapshot", {}),
            "events": session_data.get("events", []),
            "execution_complete": session_data.get("execution_complete", False),
            "execution_error": session_data.get("execution_error"),
            "layer_1_completed": session_data.get("layer_1_completed", False),
            "layer_2_completed": session_data.get("layer_2_completed", False),
            "layer_3_completed": session_data.get("layer_3_completed", False),
            "pause_after_step": session_data.get("pause_after_step", False),
            "waiting_for_review": session_data.get("pause_after_step", False),  # ✅ 派生值
        }

    except Exception as e:
        logger.error(f"Failed to load session from DB: {e}", exc_info=True)
        return None


def _add_event_to_session(session_id: str, event: Dict[str, Any]) -> bool:
    """
    Add event to session (both in-memory and database)

    Args:
        session_id: Session ID
        event: Event dictionary

    Returns:
        bool: True if successful
    """
    try:
        # Add to in-memory
        if session_id in _sessions:
            events_list = _sessions[session_id].setdefault("events", [])
            events_list.append(event)

        # Add to database
        if USE_DATABASE_PERSISTENCE:
            add_session_event(session_id, event)

        return True

    except Exception as e:
        logger.error(f"Failed to add event: {e}", exc_info=True)
        return False


def _validate_resume_state(state: Dict[str, Any], current_layer: int) -> bool:
    """
    Validate that required state is present for resume

    Args:
        state: Current state dictionary
        current_layer: Layer to resume from

    Returns:
        True if state is valid for resume
    """
    if current_layer == 2:
        # Need Layer 1 data
        return bool(state.get("analysis_report") and state.get("analysis_dimension_reports"))
    elif current_layer == 3:
        # Need Layer 1 and 2 data
        return bool(
            state.get("analysis_report") and
            state.get("analysis_dimension_reports") and
            state.get("planning_concept") and
            state.get("concept_dimension_reports")
        )
    return True


def _format_sse_json(data: Dict[str, Any]) -> str:
    """Format SSE JSON event with event type field"""
    event_type = data.get("type", "message")
    json_str = json.dumps(data, ensure_ascii=False)
    return f"event: {event_type}\ndata: {json_str}\n\n"


def _format_dimension_delta(
    dimension_key: str,
    dimension_name: str,
    layer: int,
    chunk: str,
    accumulated: str
) -> str:
    """格式化维度增量事件

    Args:
        dimension_key: 维度键
        dimension_name: 维度名称
        layer: 层级号
        chunk: 新增内容
        accumulated: 累计完整内容

    Returns:
        SSE格式的事件字符串
    """
    return _format_sse_json({
        "type": "dimension_delta",
        "data": {
            "dimension_key": dimension_key,
            "dimension_name": dimension_name,
            "layer": layer,
            "chunk": chunk,
            "accumulated": accumulated,
            "timestamp": datetime.now().isoformat()
        }
    })


def _format_dimension_complete(
    dimension_key: str,
    dimension_name: str,
    layer: int,
    full_content: str
) -> str:
    """格式化维度完成事件

    Args:
        dimension_key: 维度键
        dimension_name: 维度名称
        layer: 层级号
        full_content: 完整内容

    Returns:
        SSE格式的事件字符串
    """
    return _format_sse_json({
        "type": "dimension_complete",
        "data": {
            "dimension_key": dimension_key,
            "dimension_name": dimension_name,
            "layer": layer,
            "full_content": full_content,
            "timestamp": datetime.now().isoformat()
        }
    })


def _format_layer_progress(
    layer: int,
    completed: int,
    total: int
) -> str:
    """格式化层级进度事件

    Args:
        layer: 层级号
        completed: 已完成的维度数
        total: 总维度数

    Returns:
        SSE格式的事件字符串
    """
    return _format_sse_json({
        "type": "layer_progress",
        "data": {
            "layer": layer,
            "completed": completed,
            "total": total,
            "percentage": int((completed / total * 100)) if total > 0 else 0,
            "timestamp": datetime.now().isoformat()
        }
    })


def _build_initial_state(request: StartPlanningRequest, session_id: str) -> Dict[str, Any]:
    """
    Build initial state for main graph execution

    Consolidates all state initialization logic in one place for better maintainability.

    Args:
        request: Planning request with user inputs
        session_id: Unique session identifier

    Returns:
        Complete initial state dictionary
    """
    output_manager = create_output_manager(
        project_name=request.project_name,
        custom_output_path=str(_get_session_path(request.project_name, session_id))
    )

    # Register output_manager to global registry
    from src.utils.output_manager_registry import get_output_manager_registry
    registry = get_output_manager_registry()
    registry.register(session_id, output_manager)

    logger.info(f"[Planning API] 构建 LangGraph 初始状态")
    logger.info(f"[Planning API] village_data 字段长度: {len(request.village_data)} 字符")

    # Web environment: Always disable interactive review
    enable_review_effective = False  # Force disable for web environment
    if request.enable_review:
        logger.info("[Planning API] Web environment detected, disabling interactive review")

    state = {
        # User input
        "project_name": request.project_name,
        "village_data": request.village_data,
        "task_description": request.task_description,
        "constraints": request.constraints,

        # Session management
        "session_id": session_id,

        # Flow control
        "current_layer": 1,
        "previous_layer": 1,  # ✅ 新增：初始化为1
        "layer_1_completed": False,
        "layer_2_completed": False,
        "layer_3_completed": False,

        # Review settings
        "need_human_review": enable_review_effective,
        "human_feedback": None,
        "need_revision": False,

        # Layer outputs
        "analysis_report": "",
        "analysis_dimension_reports": {},
        "planning_concept": "",
        "concept_dimension_reports": {},
        "detailed_plan": "",
        "detailed_dimension_reports": {},
        "final_output": "",

        # Output management - use serializable path string
        "output_path": str(output_manager.output_path),

        # Checkpoint configuration
        "checkpoint_enabled": True,
        "last_checkpoint_id": "",

        # Step mode settings
        "step_mode": request.step_mode,
        "step_level": "layer",
        "pause_after_step": False,  # ✅ Fix: Don't pause at initialization

        # Routing control flags
        "quit_requested": False,
        "trigger_rollback": False,
        "rollback_target": "",

        # Optional fields
        "required_dimensions": None,
        "enable_adapters": False,
        "adapter_config": {},

        # Messages and blackboard
        "messages": [],
        "blackboard": {},

        # Streaming output configuration
        "_streaming_enabled": request.stream_mode,
        "_token_callback_factory": None,
        "_pending_tokens": [],
    }

    logger.info(f"[Planning API] LangGraph 状态构建完成，流式输出模式: {request.stream_mode}")
    return state


# ============================================
# Background Execution Function
# ============================================

async def _execute_graph_in_background(
    session_id: str,
    graph,
    initial_state: Dict[str, Any],
    checkpointer
):
    """
    在后台执行 LangGraph 并将事件写入会话状态

    此函数由 FastAPI BackgroundTasks 调用，在独立的异步任务中运行。
    事件直接写入 _sessions[session_id]["events"] 列表，无需队列。
    """
    logger.info(f"[Planning] [{session_id}] ===== 后台执行开始 =====")
    logger.info(f"[Planning] [{session_id}] Graph 类型: {type(graph).__name__}")
    logger.info(f"[Planning] [{session_id}] Checkpointer: {checkpointer}")

    try:
        config = {"configurable": {"thread_id": session_id}}

        # Get events list reference
        events_list = _sessions[session_id]["events"]

        # Get runtime objects from session (not injected into initial_state)
        streaming_queue = _sessions[session_id].get("_streaming_queue")
        storage_pipeline = _sessions[session_id].get("_storage_pipeline")
        dimension_events = _sessions[session_id].get("_dimension_events", [])

        # ✅ Use context manager to wrap graph execution
        from src.utils.streaming_context import StreamingContext

        logger.info(f"[Planning] [{session_id}] Using StreamingContext for runtime objects")

        async with StreamingContext.set_context(
            _streaming_queue=streaming_queue,
            _storage_pipeline=storage_pipeline,
            _dimension_events=dimension_events
        ):
            # Stream graph execution within context
            logger.info(f"[Planning] [{session_id}] 开始流式执行 graph.astream()")
            stream_iterator = graph.astream(initial_state, config, stream_mode="values")

            previous_event = {}
            async for event in stream_iterator:
                # ✅ 新增：检测致命错误（quit_requested）
                if event.get("quit_requested", False):
                    error_msg = event.get("execution_error", "未知错误")
                    logger.error(f"[Planning] [{session_id}] 致命错误：{error_msg}")

                    # 更新状态为失败
                    with _sessions_lock:
                        _sessions[session_id]["status"] = TaskStatus.failed
                        _sessions[session_id]["execution_error"] = error_msg
                        _sessions[session_id]["execution_complete"] = True
                        _sessions[session_id]["pause_after_step"] = False

                    # 添加错误事件
                    fatal_error_event = {
                        "type": "fatal_error",
                        "session_id": session_id,
                        "message": error_msg,
                        "timestamp": datetime.now().isoformat()
                    }
                    events_list.append(fatal_error_event)

                    # 更新数据库
                    if USE_DATABASE_PERSISTENCE:
                        add_session_event(session_id, fatal_error_event)
                        update_planning_session(session_id, {
                            "status": TaskStatus.failed,
                            "execution_error": error_msg,
                            "execution_complete": True
                        })

                    _set_stream_state(session_id, "completed")
                    logger.info(f"[Planning] [{session_id}] ===== 执行因致命错误终止 =====")
                    return  # 终止执行

                # Detect layer completion and pause state together for atomic update
                for layer_num in [1, 2, 3]:
                now_completed = event.get(f"layer_{layer_num}_completed", False)
                was_completed = previous_event.get(f"layer_{layer_num}_completed", False)
                pause_after_step = event.get("pause_after_step", False)

                # State changed to completed - update DB immediately with pause state
                if now_completed and not was_completed:
                    logger.info(f"[Planning] [{session_id}] ✓ Layer {layer_num} completed detected in graph stream")

                    # Get report content
                    if layer_num == 1:
                        report = event.get("analysis_report", "")
                        dimension_reports = event.get("analysis_dimension_reports", {})
                    elif layer_num == 2:
                        report = event.get("planning_concept", "")
                        dimension_reports = event.get("concept_dimension_reports", {})
                    else:  # layer_num == 3
                        report = event.get("detailed_plan", "")
                        dimension_reports = event.get("detailed_dimension_reports", {})

                    # ✅ 使用增强的数据库操作（带事务保护）
                    # ✅ 明确检查步进模式：如果启用且不是最后一层，应该暂停
                    pause_mode = initial_state.get("step_mode", False)
                    is_last_layer = (layer_num == 3)
                    should_pause = pause_mode and not is_last_layer

                    # ✅ 使用新的原子更新函数
                    if USE_DATABASE_PERSISTENCE:
                        # 使用增强的数据库操作函数
                        status = "paused" if should_pause else "running"
                        success = update_session_layer_completion(
                            session_id=session_id,
                            layer_num=layer_num,
                            completed=True,
                            status=status,
                            pause_after_step=should_pause
                        )

                        if success:
                            logger.info(f"[Planning] [{session_id}] ✅ Database updated atomically: layer_{layer_num}_completed=True, status={status}, pause_after_step={should_pause}")
                        else:
                            logger.error(f"[Planning] [{session_id}] ❌ Failed to update database for layer {layer_num}")

                        # 如果有 checkpoint_id，也更新到数据库
                        if event.get("last_checkpoint_id"):
                            update_state = {
                                "last_checkpoint_id": event.get("last_checkpoint_id"),
                                "updated_at": datetime.now().isoformat()
                            }
                            update_session_state(session_id, update_state)

                    # ✅ 同步更新内存状态 (thread-safe)
                    with _sessions_lock:
                        _sessions[session_id][f"layer_{layer_num}_completed"] = True
                        _sessions[session_id]["current_layer"] = layer_num
                        _sessions[session_id]["status"] = "paused" if should_pause else "running"
                        _sessions[session_id]["pause_after_step"] = should_pause

                    # ✅ 添加调试日志
                    logger.info(f"[Planning] [{session_id}] Memory state updated: layer_{layer_num}_completed={now_completed}, pause_after_step={should_pause}")

                    # ✅ 添加 layer_report_ready 事件
                    events_list.append({
                        "type": "layer_report_ready",
                        "layer": layer_num,
                        "timestamp": datetime.now().isoformat(),
                        "message": f"Layer {layer_num} report ready for loading"
                    })
                    logger.info(f"[Planning] [{session_id}] Added layer_report_ready event for layer {layer_num}")

                    # ❌ REMOVED: Layer completion notification (handled by REST polling)
                    # Frontend receives layer completion via REST /status endpoint
                    # SSE is used only for actual streaming text content

                    # ✅ Update pause-related state (if pause_after_step was detected)
                    if pause_after_step:
                        with _sessions_lock:
                            _sessions[session_id]["pause_after_step"] = True  # ✅ 状态端点读取这里
                            _sessions[session_id]["last_checkpoint_id"] = event.get("last_checkpoint_id", "")
                            # ✅ 只同步 pause_after_step 到 initial_state（审查端点读取这里）
                            _sessions[session_id]["initial_state"]["pause_after_step"] = True
                        _set_stream_state(session_id, "paused")

                        # ❌ REMOVED: Pause notification event (handled by REST polling)
                        # Frontend receives pause state via REST /status endpoint

                        logger.info(f"[Planning] [{session_id}] ✓ Pause detected at Layer {layer_num} (atomic update)")

                        # Exit stream loop when paused
                        return

            previous_event = {
                "layer_1_completed": event.get("layer_1_completed", False),
                "layer_2_completed": event.get("layer_2_completed", False),
                "layer_3_completed": event.get("layer_3_completed", False),
            }

            # ✅ 检查是否已暂停：如果暂停则跳过完成代码
            current_status = _sessions[session_id].get("status", "")
            if current_status == "paused":
                logger.info(f"[Planning] [{session_id}] ===== 执行已暂停，不发送完成事件 =====")
                return

            # ✅ Context manager automatically cleans up here
            # End of async with StreamingContext.set_context() block

            # 发送完成事件
            logger.info(f"[Planning] [{session_id}] ===== 执行完成 =====")
            completion_event = {
                "type": "completed",
                "session_id": session_id,
                "message": "规划完成",
                "success": True,
                "timestamp": datetime.now().isoformat()
            }
            events_list.append(completion_event)

            # Sync to database
            if USE_DATABASE_PERSISTENCE:
                add_session_event(session_id, completion_event)
                update_planning_session(session_id, {
                    "status": TaskStatus.completed,
                    "execution_complete": True
                })

            # 更新会话状态 (thread-safe)
            with _sessions_lock:
                _sessions[session_id]["execution_complete"] = True
                _sessions[session_id]["status"] = TaskStatus.completed
            _set_stream_state(session_id, "completed")

            logger.info(f"[Planning] [{session_id}] 总事件数: {len(events_list)}")

    except Exception as e:
        logger.error(f"[Planning] Execution error for {session_id}: {e}", exc_info=True)

        # 添加错误事件
        error_event = {
            "type": "error",
            "session_id": session_id,
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }
        _sessions[session_id]["events"].append(error_event)

        # Sync to database
        if USE_DATABASE_PERSISTENCE:
            add_session_event(session_id, error_event)
            update_planning_session(session_id, {
                "status": TaskStatus.failed,
                "execution_complete": True,
                "execution_error": str(e)
            })

        # 更新会话状态 (thread-safe)
        with _sessions_lock:
            _sessions[session_id]["execution_complete"] = True
            _sessions[session_id]["execution_error"] = str(e)
            _sessions[session_id]["status"] = TaskStatus.failed
        _set_stream_state(session_id, "completed")


async def _resume_graph_execution(session_id: str, state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Resume graph execution with restored state (simplified version)

    Args:
        session_id: Session identifier
        state: Current state dictionary

    Returns:
        Response with stream URL for resuming execution

    Note: This function is used for reject/revision scenarios.
    For approve scenarios, the logic is inlined in review_action.
    """
    from langgraph.checkpoint.memory import MemorySaver

    # Validate state before resuming
    current_layer = state.get("current_layer", 1)
    if not _validate_resume_state(state, current_layer):
        logger.error(f"[Planning API] Invalid state for resume at layer {current_layer}")
        raise HTTPException(
            status_code=400,
            detail=f"Cannot resume at layer {current_layer}: missing required data"
        )

    # Retrieve existing checkpointer (required for resume)
    checkpointer = _session_checkpointer.get(session_id)
    if not checkpointer:
        logger.warning(f"[Planning API] No checkpointer found for session {session_id}, creating new one")
        checkpointer = MemorySaver()
        _session_checkpointer[session_id] = checkpointer

    # Update session state (preserve events list)
    if session_id in _sessions:
        _sessions[session_id]["initial_state"] = state
        _sessions[session_id]["current_layer"] = current_layer
        # ✅ 不清空事件列表，保留已有事件
        # _sessions[session_id]["events"] = []  # REMOVED
        _sessions[session_id]["execution_complete"] = False
        _sessions[session_id]["execution_error"] = None
        _sessions[session_id]["status"] = TaskStatus.running

    # ✅ 关键：重新初始化流式组件并保存到session（不注入到state）
    try:
        # 创建新的流式队列
        async def sse_flush_callback(tokens: list[str]):
            """SSE flush callback for streaming"""
            from .sessions import _format_sse_json
            event = _format_sse_json({
                "type": "text_delta",
                "tokens": tokens,
                "session_id": session_id,
                "timestamp": datetime.now().isoformat()
            })
            _sessions[session_id]["events"].append(event)

        streaming_queue = StreamingQueueManager(
            batch_size=50,
            batch_window=0.1,
            flush_callback=sse_flush_callback
        )

        # 创建新的异步存储管道
        storage_pipeline = await create_storage_pipeline(
            session_id=session_id,
            project_name=state.get("project_name", "default"),
            enable_redis=True
        )

        # 保留现有的 dimension_events（如果存在）
        dimension_events = state.get("_dimension_events", [])

        # ✅ 保存流式组件引用到session（不注入到state）
        _sessions[session_id]["_streaming_queue"] = streaming_queue
        _sessions[session_id]["_storage_pipeline"] = storage_pipeline
        _sessions[session_id]["_dimension_events"] = dimension_events

        logger.info(f"[Planning API] [{session_id}] 流式组件已保存到session (resume)")

    except Exception as e:
        logger.warning(f"[Planning API] [{session_id}] 流式组件重新初始化失败: {e}，将使用传统模式")
        # Set to None if initialization fails
        _sessions[session_id]["_streaming_queue"] = None
        _sessions[session_id]["_storage_pipeline"] = None
        _sessions[session_id]["_dimension_events"] = []

    # Create graph
    graph = create_village_planning_graph(checkpointer=checkpointer)

    # Reset stream state (thread-safe)
    _set_stream_state(session_id, "active")

    # Start background execution directly
    asyncio.create_task(
        _execute_graph_in_background(session_id, graph, state, checkpointer)
    )

    logger.info(f"[Planning API] Resumed background execution for session {session_id}")

    return {
        "message": "Execution resumed",
        "session_id": session_id,
        "stream_url": f"/api/planning/stream/{session_id}",
        "current_layer": current_layer,
        "resumed": True
    }


# ============================================
# API Endpoints
# ============================================

@router.post("/api/planning/start")
async def start_planning(
    request: StartPlanningRequest,
    background_tasks: BackgroundTasks
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
        allowed, message = rate_limiter.check_rate_limit(
            project_name=request.project_name,
            session_id=""  # session_id not yet generated
        )

        if not allowed:
            logger.warning(f"[Planning API] 限流触发: {message}")

            # Calculate retry-after time if available
            retry_after = rate_limiter.get_retry_after(request.project_name)

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
        rate_limiter.mark_task_started(request.project_name)

        # Build initial state
        initial_state = _build_initial_state(request, session_id)
        logger.info(f"[Planning API] 初始状态构建完成")

        # Create checkpointer and graph
        from langgraph.checkpoint.memory import MemorySaver
        checkpointer = MemorySaver()
        _session_checkpointer[session_id] = checkpointer

        logger.info(f"[Planning API] 创建 LangGraph 实例")
        graph = create_village_planning_graph(checkpointer=checkpointer)

        # Save to database
        if USE_DATABASE_PERSISTENCE:
            try:
                initial_state["_request_params"] = request.model_dump()
                create_planning_session(initial_state)
                logger.info(f"[Planning API] Session saved to database: {session_id}")
            except Exception as e:
                logger.error(f"[Planning API] Failed to save session to database: {e}")
                # Continue anyway, in-memory storage will work

        # Initialize session with events list
        _sessions[session_id] = {
            "session_id": session_id,
            "project_name": request.project_name,
            "status": TaskStatus.running,
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "request": request.model_dump(),
            "current_layer": 1,
            "initial_state": initial_state,
            "events": [],  # Store events directly in session
            "execution_complete": False,
            "execution_error": None,
            "layer_1_completed": False,
            "layer_2_completed": False,
            "layer_3_completed": False,
            "pause_after_step": False,
            "waiting_for_review": False,
        }

        # Mark execution as active (thread-safe)
        _set_execution_active(session_id, True)

        # 创建流式队列管理器（如果启用流式模式）
        streaming_queue = None
        storage_pipeline = None
        dimension_events = []
        if request.stream_mode:
            try:
                from src.utils.streaming_queue import StreamingQueueManager
                from backend.services.storage_pipeline import create_storage_pipeline

                # 创建事件队列用于SSE推送
                dimension_events: list[Dict[str, Any]] = []

                def sse_flush_callback(**kwargs):
                    """维度内容刷新回调 - 添加到SSE事件队列"""
                    dimension_events.append({
                        "type": "dimension_delta",
                        "data": kwargs
                    })

                streaming_queue = StreamingQueueManager(
                    batch_size=50,
                    batch_window=0.1,
                    flush_callback=sse_flush_callback
                )

                # 创建异步存储管道
                storage_pipeline = await create_storage_pipeline(
                    session_id=session_id,
                    project_name=request.project_name,
                    enable_redis=True
                )

                # ✅ 不注入到initial_state，只保存到session
                logger.info(f"[Planning API] 流式队列和存储管道已初始化")

            except Exception as e:
                logger.warning(f"[Planning API] 流式组件初始化失败: {e}，将使用传统模式")

        # ✅ 保存流式组件引用到session（不注入到initial_state）
        _sessions[session_id]["_streaming_queue"] = streaming_queue
        _sessions[session_id]["_storage_pipeline"] = storage_pipeline
        _sessions[session_id]["_dimension_events"] = dimension_events

        # Start background execution (non-blocking)
        background_tasks.add_task(
            _execute_graph_in_background,
            session_id,
            graph,
            initial_state,
            checkpointer
        )

        elapsed = (time.time() - start_time) * 1000
        logger.info(f"[Planning API] 后台任务已提交，立即返回响应 ({elapsed:.2f}ms)")

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
    """
    SSE stream - 支持维度级流式推送

    Event Types:
    - connected: Connection established
    - text_delta: Token-level streaming for typewriter effect (legacy)
    - dimension_delta: 维度级增量内容
    - dimension_complete: 维度完成
    - layer_progress: 层级进度
    - error: Immediate error notification

    其他事件 (layer_completed, pause, completed) 由 REST polling 处理
    """
    if session_id not in _sessions:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    logger.info(f"[Planning API] [{session_id}] ===== SSE 连接建立 =====")

    async def event_generator():
        try:
            # Send connected event
            yield _format_sse_json({
                "type": "connected",
                "session_id": session_id,
                "timestamp": datetime.now().isoformat()
            })
            logger.info(f"[Planning API] [{session_id}] 已发送 'connected' 事件")

            event_index = 0
            dimension_event_index = 0

            while True:
                # Check if session deleted
                if session_id not in _sessions:
                    logger.warning(f"[Planning] Session {session_id} deleted, closing stream")
                    break

                session = _sessions[session_id]
                events_list = session.get("events", [])
                dimension_events = session.get("_dimension_events", [])

                # Send new dimension events (优先处理维度事件)
                while dimension_event_index < len(dimension_events):
                    event = dimension_events[dimension_event_index]
                    event_type = event.get("type")

                    if event_type == "dimension_delta":
                        data = event.get("data", {})
                        yield _format_dimension_delta(
                            dimension_key=data.get("dimension_key", ""),
                            dimension_name=data.get("dimension_name", ""),
                            layer=data.get("layer", 1),
                            chunk=data.get("chunk", ""),
                            accumulated=data.get("accumulated", "")
                        )
                        dimension_event_index += 1

                    elif event_type == "dimension_complete":
                        data = event.get("data", {})
                        yield _format_dimension_complete(
                            dimension_key=data.get("dimension_key", ""),
                            dimension_name=data.get("dimension_name", ""),
                            layer=data.get("layer", 1),
                            full_content=data.get("full_content", "")
                        )
                        dimension_event_index += 1

                    elif event_type == "layer_progress":
                        data = event.get("data", {})
                        yield _format_layer_progress(
                            layer=data.get("layer", 1),
                            completed=data.get("completed", 0),
                            total=data.get("total", 0)
                        )
                        dimension_event_index += 1

                    else:
                        # 其他维度事件直接转发
                        yield _format_sse_json(event)
                        dimension_event_index += 1

                # Send legacy text_delta events
                while event_index < len(events_list):
                    event = events_list[event_index]
                    event_type = event.get("type")

                    # ✅ Only send text_delta events
                    if event_type == "text_delta":
                        yield _format_sse_json(event)
                        event_index += 1

                    # ✅ Keep error for immediate notification
                    elif event_type == "error":
                        yield _format_sse_json(event)
                        event_index += 1
                        return

                    # ❌ Skip all other events (handled by REST polling)
                    elif event_type in ["layer_completed", "pause", "stream_paused", "completed"]:
                        event_index += 1
                        logger.debug(f"[Planning API] [{session_id}] 跳过事件 {event_type} (由 REST 处理)")

                    else:
                        # Forward any other events
                        yield _format_sse_json(event)
                        event_index += 1

                # Send heartbeat
                yield ": keep-alive\n\n"
                await asyncio.sleep(1)

        except asyncio.CancelledError:
            logger.info(f"[Planning] SSE client disconnected: {session_id}")
        except Exception as e:
            logger.error(f"[Planning] SSE error for {session_id}: {e}", exc_info=True)
            yield _format_sse_json({
                "type": "error",
                "session_id": session_id,
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            })

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


@router.post("/api/planning/review/{session_id}")
async def review_action(session_id: str, request: ReviewActionRequest):
    """
    Handle review actions from web frontend

    Actions:
    - approve: Continue execution
    - reject: Submit feedback and trigger revision
    - rollback: Rollback to checkpoint
    """
    try:
        if session_id not in _sessions:
            raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

        session = _sessions[session_id]
        initial_state = session.get("initial_state", {})
        review_id = initial_state.get("review_id", "")

        # ✅ 只检查 pause_after_step（单一数据源）
        is_pause_mode = (
            initial_state.get("pause_after_step", False) or
            session.get("pause_after_step", False)  # ✅ 也检查顶层属性
        )
        # ❌ 删除：is_review_mode = initial_state.get("waiting_for_review", False)

        if not review_id and not is_pause_mode and request.action != "rollback":
            raise HTTPException(status_code=400, detail="No pending review or pause")

        from src.tools.web_review_tool import WebReviewTool
        web_review_tool = WebReviewTool()

        if request.action == "approve":
            # ✅ 添加：详细日志记录批准前的状态
            logger.info(f"[Planning API] [{session_id}] 批准请求 - 状态检查")
            logger.info(f"[Planning API] [{session_id}]   - review_id: {review_id}")
            logger.info(f"[Planning API] [{session_id}]   - pause_after_step: {is_pause_mode}")
            logger.info(f"[Planning API] [{session_id}]   - current_layer: {initial_state.get('current_layer', 1)}")

            # 1. 重置暂停标志（保持单一数据源）
            _sessions[session_id]["pause_after_step"] = False
            _sessions[session_id]["initial_state"]["pause_after_step"] = False
            _sessions[session_id]["initial_state"]["__interrupt__"] = False
            _sessions[session_id]["initial_state"]["human_feedback"] = ""

            # 2. 确保 current_layer 正确递增
            current_layer = initial_state.get("current_layer", 1)
            if current_layer == 1 and initial_state.get("layer_1_completed", False):
                initial_state["current_layer"] = 2
                _sessions[session_id]["current_layer"] = 2
                logger.info(f"[Planning API] [{session_id}] Layer 1完成，进入Layer 2")
            elif current_layer == 2 and initial_state.get("layer_2_completed", False):
                initial_state["current_layer"] = 3
                _sessions[session_id]["current_layer"] = 3
                logger.info(f"[Planning API] [{session_id}] Layer 2完成，进入Layer 3")
            elif current_layer == 3 and initial_state.get("layer_3_completed", False):
                initial_state["current_layer"] = 4
                _sessions[session_id]["current_layer"] = 4
                logger.info(f"[Planning API] [{session_id}] Layer 3完成，进入最终阶段")

            # 3. 清除退出标志（允许继续执行）
            initial_state["quit_requested"] = False

            # 4. 获取原 checkpointer 实例（不重新创建）
            checkpointer = _session_checkpointer.get(session_id)
            if not checkpointer:
                logger.error(f"[Planning API] [{session_id}] No checkpointer found for session")
                raise HTTPException(status_code=500, detail="Graph not found for session")

            # 5. 提交审查决策（如果启用）
            if review_id:
                web_review_tool.submit_review_decision(review_id=review_id, action="approve")

            logger.info(f"[Planning API] [{session_id}] Approving and continuing execution (Layer {initial_state.get('current_layer', 1)})")

            # 6. 重置 stream 状态
            _set_stream_state(session_id, "active")

            # 7. 更新会话状态
            _sessions[session_id]["status"] = TaskStatus.running

            # 8. 更新数据库状态
            if USE_DATABASE_PERSISTENCE:
                update_planning_session(session_id, {
                    "status": TaskStatus.running,
                    "pause_after_step": False,
                    "current_layer": initial_state.get("current_layer", 1)
                })

            # 9. ✅ 关键：重新初始化流式组件并保存到session（不注入到state）
            try:
                # 创建新的流式队列
                async def sse_flush_callback(tokens: list[str]):
                    """SSE flush callback for streaming"""
                    from .sessions import _format_sse_json
                    event = _format_sse_json({
                        "type": "text_delta",
                        "tokens": tokens,
                        "session_id": session_id,
                        "timestamp": datetime.now().isoformat()
                    })
                    _sessions[session_id]["events"].append(event)

                streaming_queue = StreamingQueueManager(
                    batch_size=50,
                    batch_window=0.1,
                    flush_callback=sse_flush_callback
                )

                # 创建新的异步存储管道
                storage_pipeline = await create_storage_pipeline(
                    session_id=session_id,
                    project_name=initial_state.get("project_name", "default"),
                    enable_redis=True
                )

                # 保留现有的 dimension_events（如果存在）
                dimension_events = initial_state.get("_dimension_events", [])

                # ✅ 保存流式组件引用到session（不注入到initial_state）
                _sessions[session_id]["_streaming_queue"] = streaming_queue
                _sessions[session_id]["_storage_pipeline"] = storage_pipeline
                _sessions[session_id]["_dimension_events"] = dimension_events

                logger.info(f"[Planning API] [{session_id}] 流式组件已保存到session")

            except Exception as e:
                logger.warning(f"[Planning API] [{session_id}] 流式组件重新初始化失败: {e}，将使用传统模式")
                # Set to None if initialization fails
                _sessions[session_id]["_streaming_queue"] = None
                _sessions[session_id]["_storage_pipeline"] = None
                _sessions[session_id]["_dimension_events"] = []

            # 10. 创建新 graph 并启动后台执行
            graph = create_village_planning_graph(checkpointer=checkpointer)

            # 启动后台执行
            asyncio.create_task(
                _execute_graph_in_background(session_id, graph, initial_state, checkpointer)
            )

            logger.info(f"[Planning API] [{session_id}] Background execution started for Layer {initial_state.get('current_layer', 1)}")

            # 10. 返回成功响应（前端通过轮询 /status 检测状态变化）
            return {
                "message": f"Execution continuing to Layer {initial_state.get('current_layer', 1)}",
                "session_id": session_id,
                "status": TaskStatus.running,
                "current_layer": initial_state.get("current_layer", 1),
                "resumed": True
            }

        elif request.action == "reject":
            # ✅ 关键：清理单一数据源时，务必清理两个物理位置
            _sessions[session_id]["pause_after_step"] = False  # 主会话字段
            _sessions[session_id]["initial_state"]["pause_after_step"] = False  # initial_state
            _sessions[session_id]["initial_state"]["human_feedback"] = request.feedback
            _sessions[session_id]["initial_state"]["need_revision"] = True
            _sessions[session_id]["initial_state"]["revision_target_dimensions"] = request.dimensions
            _sessions[session_id]["initial_state"]["__interrupt__"] = False
            _sessions[session_id]["status"] = TaskStatus.revising

            if review_id:
                web_review_tool.submit_review_decision(
                    review_id=review_id,
                    action="reject",
                    feedback=request.feedback,
                    target_dimensions=request.dimensions
                )

            logger.info(f"[Planning API] Review rejected with feedback, session {session_id}")

            # Trigger graph re-invocation for revision
            return await _resume_graph_execution(session_id, initial_state)

        elif request.action == "rollback":
            if not request.checkpoint_id:
                raise HTTPException(status_code=400, detail="Checkpoint ID required for rollback")

            project_name = session.get("project_name", "")
            checkpoint_tool = tool_manager.get_checkpoint_tool(project_name)
            rollback_result = checkpoint_tool.rollback(
                checkpoint_id=request.checkpoint_id,
                current_output_dir=None
            )

            if not rollback_result.get("success"):
                raise HTTPException(
                    status_code=400,
                    detail=f"Rollback failed: {rollback_result.get('error', 'Unknown error')}"
                )

            if review_id:
                web_review_tool.submit_review_decision(
                    review_id=review_id,
                    action="rollback",
                    checkpoint_id=request.checkpoint_id
                )

            state = rollback_result.get("state", {})
            initial_state.update(state)
            session["current_layer"] = state.get("current_layer", 1)
            session["status"] = TaskStatus.paused

            logger.info(f"[Planning API] Rolling back session {session_id}")

            return {
                "message": f"Rolling back to checkpoint {request.checkpoint_id}",
                "resumed": True
            }

        else:
            raise HTTPException(status_code=400, detail=f"Invalid action: {request.action}")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[Planning API] Review action error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Review action failed: {str(e)}")


@router.get("/api/planning/status/{session_id}", response_model=SessionStatusResponse)
async def get_status(session_id: str):
    """
    Get session status

    Returns current status, progress, and checkpoint information.
    """
    try:
        if session_id not in _sessions:
            raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

        session = _sessions[session_id]
        project_name = session.get("project_name", "")

        # ✅ 添加调试日志
        layer_1_completed = session.get("layer_1_completed", False)
        layer_2_completed = session.get("layer_2_completed", False)
        layer_3_completed = session.get("layer_3_completed", False)
        status = session.get("status", "pending")
        pause_after_step = session.get("pause_after_step", False)

        logger.debug(f"[Planning API] Status for {session_id}: "
                    f"L1={layer_1_completed}, L2={layer_2_completed}, L3={layer_3_completed}, "
                    f"status={status}, pause={pause_after_step}")

        # Get checkpoints
        checkpoints = []
        if project_name:
            try:
                checkpoint_tool = tool_manager.get_checkpoint_tool(project_name)
                list_result = checkpoint_tool.list(include_all=True)
                if list_result.get("success"):
                    checkpoints = list_result.get("checkpoints", [])
            except Exception as e:
                logger.warning(f"Failed to load checkpoints: {e}")

        current_layer = session.get("current_layer")
        progress = calculate_progress(current_layer)

        # Get layer completion states (already declared above)
        # layer_1_completed = session.get("layer_1_completed", False)
        # layer_2_completed = session.get("layer_2_completed", False)
        # layer_3_completed = session.get("layer_3_completed", False)

        # Get pause/review states (already declared above)
        # pause_after_step = session.get("pause_after_step", False)
        waiting_for_review = pause_after_step  # ✅ 派生值，不再独立存储
        last_checkpoint_id = session.get("last_checkpoint_id")

        # Get execution states
        execution_error = session.get("execution_error")
        execution_complete = session.get("execution_complete", False)
        updated_at = session.get("updated_at", session.get("created_at", ""))

        return SessionStatusResponse(
            session_id=session_id,
            status=session.get("status", TaskStatus.pending),
            current_layer=current_layer,
            created_at=session.get("created_at", ""),
            checkpoints=checkpoints,
            checkpoint_count=len(checkpoints),
            progress=progress,
            layer_1_completed=layer_1_completed,
            layer_2_completed=layer_2_completed,
            layer_3_completed=layer_3_completed,
            pause_after_step=pause_after_step,
            waiting_for_review=waiting_for_review,
            last_checkpoint_id=last_checkpoint_id,
            execution_error=execution_error,
            execution_complete=execution_complete,
            updated_at=updated_at
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[Planning API] Status error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Status fetch failed: {str(e)}")


@router.delete("/api/planning/sessions/{session_id}")
async def delete_session(session_id: str):
    """
    Delete a session

    Removes session from memory and cleans up checkpointer.
    Checkpoint data is preserved by default.
    """
    try:
        if session_id not in _sessions:
            raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

        del _sessions[session_id]

        # Clean up checkpointer
        if session_id in _session_checkpointer:
            del _session_checkpointer[session_id]
            logger.info(f"[Planning API] Cleaned up checkpointer for session {session_id}")

        # Clean up active execution flag
        if session_id in _active_executions:
            del _active_executions[session_id]

        # Clean up stream state
        if session_id in _stream_states:
            del _stream_states[session_id]

        logger.info(f"[Planning API] Session {session_id} deleted")

        return {"message": f"Session {session_id} deleted"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[Planning API] Delete session error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to delete session: {str(e)}")


@router.post("/api/planning/resume")
async def resume_from_checkpoint(request: ResumeRequest):
    """
    Resume execution from checkpoint

    Loads checkpoint state and creates new session for continued execution.
    """
    try:
        session_id = _generate_session_id()
        logger.info(f"[Planning API] Resuming from checkpoint {request.checkpoint_id}")

        checkpoint_tool = tool_manager.get_checkpoint_tool(request.project_name)
        load_result = checkpoint_tool.load(request.checkpoint_id)

        if not load_result.get("success"):
            raise HTTPException(
                status_code=404,
                detail=f"Checkpoint not found: {request.checkpoint_id}"
            )

        state = load_result.get("state", {})
        metadata = load_result.get("metadata", {})

        _sessions[session_id] = {
            "session_id": session_id,
            "project_name": request.project_name,
            "status": TaskStatus.running,
            "created_at": datetime.now().isoformat(),
            "resumed_from": request.checkpoint_id,
            "current_layer": metadata.get("layer", 1),
            "initial_state": state,
            "events": [],
            "execution_complete": False,
            "execution_error": None,
        }

        return {
            "session_id": session_id,
            "status": TaskStatus.running,
            "message": f"Resumed from Layer {metadata.get('layer', 1)}",
            "stream_url": f"/api/planning/stream/{session_id}",
            "current_layer": metadata.get("layer", 1)
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[Planning API] Resume error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Resume failed: {str(e)}")


@router.get("/api/planning/checkpoints/{project_name}")
async def list_checkpoints(project_name: str):
    """
    List all checkpoints for a project
    """
    try:
        checkpoint_tool = tool_manager.get_checkpoint_tool(project_name)
        list_result = checkpoint_tool.list(include_all=True)

        if not list_result.get("success"):
            return {
                "project_name": project_name,
                "checkpoints": [],
                "error": list_result.get("error", "Unknown error"),
                "count": 0
            }

        return {
            "project_name": project_name,
            "checkpoints": list_result.get("checkpoints", []),
            "count": list_result.get("count", 0)
        }

    except Exception as e:
        logger.error(f"[Planning API] List checkpoints error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to list checkpoints: {str(e)}")


# ============================================
# Management Endpoints (for monitoring)
# ============================================

@router.get("/api/planning/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "active_sessions": len(_sessions),
        "timestamp": datetime.now().isoformat()
    }


@router.get("/api/planning/sessions")
async def list_sessions():
    """List all active sessions (for debugging)"""
    return {
        "sessions": list(_sessions.keys()),
        "count": len(_sessions)
    }


@router.get("/api/planning/rate-limit/status")
async def get_rate_limit_status():
    """Get rate limit status (for monitoring)"""
    return rate_limiter.get_status()


@router.post("/api/planning/rate-limit/reset/{project_name}")
async def reset_rate_limit(project_name: str):
    """Reset rate limit status for a project (admin function)"""
    success = rate_limiter.reset_project(project_name)
    if success:
        return {"message": f"已重置项目 '{project_name}' 的限流状态"}
    else:
        raise HTTPException(status_code=404, detail=f"项目不存在: {project_name}")


# ============================================
# Session Cleanup Mechanism
# ============================================

SESSION_EXPIRATION_HOURS = 24  # Sessions expire after 24 hours
CLEANUP_INTERVAL_SECONDS = 3600  # Check every hour

_cleanup_task: Optional[asyncio.Task] = None


async def _cleanup_expired_sessions() -> None:
    """后台任务：清理过期会话"""
    while True:
        try:
            await asyncio.sleep(CLEANUP_INTERVAL_SECONDS)

            current_time = time.time()
            expired_sessions = []

            with _sessions_lock:
                for session_id, session_data in _sessions.items():
                    created_at_str = session_data.get("created_at", "")
                    try:
                        created_at = datetime.fromisoformat(created_at_str.replace('Z', '+00:00'))
                        age_hours = (current_time - created_at.timestamp()) / 3600

                        if age_hours > SESSION_EXPIRATION_HOURS:
                            expired_sessions.append(session_id)
                    except Exception as e:
                        logger.warning(f"[Cleanup] Failed to parse created_at for {session_id}: {e}")

                # 删除过期会话
                for session_id in expired_sessions:
                    del _sessions[session_id]
                    # 清理关联状态
                    if session_id in _session_checkpointer:
                        del _session_checkpointer[session_id]
                    if session_id in _active_executions:
                        del _active_executions[session_id]
                    if session_id in _stream_states:
                        del _stream_states[session_id]

            if expired_sessions:
                logger.info(f"[Cleanup] Cleaned up {len(expired_sessions)} expired sessions")

        except asyncio.CancelledError:
            logger.info("[Cleanup] Session cleanup task cancelled")
            break
        except Exception as e:
            logger.error(f"[Cleanup] Session cleanup error: {e}", exc_info=True)


async def start_session_cleanup() -> None:
    """启动会话清理后台任务"""
    global _cleanup_task
    if _cleanup_task is None or _cleanup_task.done():
        _cleanup_task = asyncio.create_task(_cleanup_expired_sessions())
        logger.info("[Cleanup] Session cleanup task started")


async def stop_session_cleanup() -> None:
    """停止会话清理后台任务"""
    global _cleanup_task
    if _cleanup_task and not _cleanup_task.done():
        _cleanup_task.cancel()
        try:
            await _cleanup_task
        except asyncio.CancelledError:
            pass
        logger.info("[Cleanup] Session cleanup task stopped")


@router.post("/api/planning/admin/cleanup")
async def manual_cleanup():
    """手动触发会话清理（管理员功能）"""
    current_time = time.time()
    expired_sessions = []

    with _sessions_lock:
        for session_id, session_data in _sessions.items():
            created_at_str = session_data.get("created_at", "")
            try:
                created_at = datetime.fromisoformat(created_at_str.replace('Z', '+00:00'))
                age_hours = (current_time - created_at.timestamp()) / 3600

                if age_hours > SESSION_EXPIRATION_HOURS:
                    expired_sessions.append(session_id)
            except Exception:
                pass

        # 删除过期会话
        for session_id in expired_sessions:
            del _sessions[session_id]
            if session_id in _session_checkpointer:
                del _session_checkpointer[session_id]
            if session_id in _active_executions:
                del _active_executions[session_id]
            if session_id in _stream_states:
                del _stream_states[session_id]

    return {
        "cleaned": len(expired_sessions),
        "expired_sessions": expired_sessions,
        "message": f"Cleaned up {len(expired_sessions)} expired sessions"
    }


__all__ = ["router", "start_session_cleanup", "stop_session_cleanup"]
