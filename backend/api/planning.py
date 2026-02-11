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
from collections import deque
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Any, Dict, Generator, List, Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from backend.api.tool_manager import tool_manager
from backend.schemas import TaskStatus
from backend.services.rate_limiter import rate_limiter
from backend.utils.progress_helper import calculate_progress
from backend.utils.logging import _extract_session_id
from src.orchestration.main_graph import create_village_planning_graph
from src.utils.output_manager import create_output_manager
from src.utils.paths import get_results_dir

router = APIRouter()
logger = logging.getLogger(__name__)

# Configuration constants
MAX_SESSION_EVENTS = 1000  # Maximum events to keep per session (约 30 分钟流式事件)
EVENT_CLEANUP_INTERVAL_SECONDS = 300  # Cleanup interval: 5 minutes (instead of 1 hour)

# In-memory session storage (for production: use Redis)
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


# ============================================
# Helper Functions
# ============================================

# Thread-safe session access helpers
def _get_session_value(session_id: str, key: str, default=None) -> Any:
    """
    Thread-safe get session value

    Args:
        session_id: Session identifier
        key: Session key to retrieve
        default: Default value if key not found

    Returns:
        Session value or default
    """
    with _sessions_lock:
        if session_id not in _sessions:
            return default
        return _sessions[session_id].get(key, default)


def _set_session_value(session_id: str, key: str, value: Any) -> bool:
    """
    Thread-safe set session value

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


def _append_session_event(session_id: str, event: Dict) -> None:
    """
    Thread-safe append event to session events list

    Args:
        session_id: Session identifier
        event: Event dictionary to append
    """
    with _sessions_lock:
        if session_id in _sessions:
            _sessions[session_id].setdefault("events", []).append(event)


def _get_session_events_copy(session_id: str) -> list:
    """
    Thread-safe get copy of session events list

    Args:
        session_id: Session identifier

    Returns:
        Copy of events list or empty list if session not found
    """
    with _sessions_lock:
        if session_id not in _sessions:
            return []
        return list(_sessions[session_id].get("events", []))


def _is_execution_active(session_id: str) -> bool:
    """
    Thread-safe check if execution is active

    Args:
        session_id: Session identifier

    Returns:
        True if execution is active
    """
    with _active_executions_lock:
        return _active_executions.get(session_id, False)


def _set_execution_active(session_id: str, active: bool) -> None:
    """
    Thread-safe set execution active state

    Args:
        session_id: Session identifier
        active: Active state to set
    """
    with _active_executions_lock:
        _active_executions[session_id] = active


def _get_stream_state(session_id: str) -> str:
    """
    Thread-safe get stream state

    Args:
        session_id: Session identifier

    Returns:
        Stream state: "active", "paused", or "completed"
    """
    with _stream_states_lock:
        return _stream_states.get(session_id, "active")


def _set_stream_state(session_id: str, state: str) -> None:
    """
    Thread-safe set stream state

    Args:
        session_id: Session identifier
        state: New stream state
    """
    with _stream_states_lock:
        _stream_states[session_id] = state


def _generate_session_id() -> str:
    """Generate session ID (timestamp format)"""
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _get_session_path(project_name: str, session_id: str) -> Path:
    """Get file system path for session"""
    safe_name = project_name.replace('/', '_').replace('\\', '_').replace(':', '_')
    return get_results_dir() / safe_name / session_id


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

        # 获取会话事件列表的引用
        events_list = _get_session_events_copy(session_id)
        # Get or initialize the set of sent layer events
        sent_events = _get_session_value(session_id, "sent_layer_events", set())
        logger.info(f"[Planning] [{session_id}] 已发送的layer事件: {sent_events}")
        # Get or initialize the set of sent pause events
        sent_pause_events = _get_session_value(session_id, "sent_pause_events", set())
        logger.info(f"[Planning] [{session_id}] 已发送的pause事件: {sent_pause_events}")

        # 流式执行图
        logger.info(f"[Planning] [{session_id}] 开始流式执行 graph.astream()")
        stream_iterator = graph.astream(initial_state, config, stream_mode="values")

        previous_event = {}
        async for event in stream_iterator:
            # 检测层级完成
            for layer_num in [1, 2, 3]:
                now_completed = event.get(f"layer_{layer_num}_completed", False)
                was_completed = previous_event.get(f"layer_{layer_num}_completed", False)

                # 事件key用于去重追踪
                event_key = f"layer_{layer_num}_completed"

                # 检查：状态变化 + 未发送过
                if now_completed and not was_completed and event_key not in sent_events:
                    # 获取报告内容
                    if layer_num == 1:
                        report = event.get("analysis_report", "")
                        dimension_reports = event.get("analysis_dimension_reports", {})
                    elif layer_num == 2:
                        report = event.get("planning_concept", "")
                        dimension_reports = event.get("concept_dimension_reports", {})
                    else:  # layer_num == 3
                        report = event.get("detailed_plan", "")
                        dimension_reports = event.get("detailed_dimension_reports", {})

                    # 生成事件并添加到会话事件列表
                    event_data = {
                        "type": "layer_completed",
                        "layer": layer_num,
                        "layer_number": layer_num,
                        "session_id": session_id,
                        "message": f"Layer {layer_num} completed",
                        "report_content": report[:500000],  # Truncate if too large
                        "dimension_reports": dimension_reports,
                        "timestamp": datetime.now().isoformat()
                    }
                    _append_session_event(session_id, event_data)
                    sent_events.add(event_key)  # 标记已发送
                    logger.info(f"[Planning] [{session_id}] ✓ layer_completed 事件已添加到队列")
                    logger.info(f"[Planning] [{session_id}]   - Layer {layer_num}")
                    logger.info(f"[Planning] [{session_id}]   - 队列长度: {len(events_list)}")
                    logger.info(f"[Planning] [{session_id}]   - 报告长度: {len(report)} 字符")
                    logger.info(f"[Planning] [{session_id}]   - 维度报告数量: {len(dimension_reports)}")
                    logger.info(f"[Planning] [{session_id}]   - 已发送事件: {sent_events}")
                elif now_completed and event_key in sent_events:
                    # 重复事件检测
                    logger.info(f"[Planning] [{session_id}] ⚠️ 跳过重复的 layer_{layer_num}_completed 事件")
                    logger.info(f"[Planning] [{session_id}]   - 事件已在已发送列表中: {sent_events}")

            previous_event = {
                "layer_1_completed": event.get("layer_1_completed", False),
                "layer_2_completed": event.get("layer_2_completed", False),
                "layer_3_completed": event.get("layer_3_completed", False),
            }

            # 检查暂停状态（步进模式）
            if event.get("pause_after_step"):
                current_layer = event.get("current_layer", 1)

                # ✅ 添加：pause事件去重
                pause_event_key = f"pause_layer_{current_layer}"

                if pause_event_key not in sent_pause_events:
                    # 首次检测到此layer的暂停，添加事件
                    pause_event = {
                        "type": "pause",
                        "session_id": session_id,
                        "current_layer": current_layer,
                        "checkpoint_id": event.get("last_checkpoint_id", ""),
                        "reason": "step_mode",
                        "timestamp": datetime.now().isoformat()
                    }
                    _append_session_event(session_id, pause_event)
                    sent_pause_events.add(pause_event_key)  # ✅ 标记已发送

                    stream_paused_event = {
                        "type": "stream_paused",
                        "session_id": session_id,
                        "current_layer": current_layer,
                        "reason": "waiting_for_resume",
                        "timestamp": datetime.now().isoformat()
                    }
                    _append_session_event(session_id, stream_paused_event)

                    _stream_states[session_id] = "paused"
                    logger.info(f"[Planning] [{session_id}] ✓ pause事件已添加到队列 (Layer {current_layer})")
                    logger.info(f"[Planning] [{session_id}]   - 已发送pause事件: {sent_pause_events}")
                else:
                    # ⚠️ 重复pause事件，跳过
                    logger.info(f"[Planning] [{session_id}] ⚠️ 跳过重复的pause事件 (Layer {current_layer})")
                    logger.info(f"[Planning] [{session_id}]   - 事件已在已发送列表中: {sent_pause_events}")

                return

        # 发送完成事件
        logger.info(f"[Planning] [{session_id}] ===== 执行完成 =====")
        completion_event = {
            "type": "completed",
            "session_id": session_id,
            "message": "规划完成",
            "success": True,
            "timestamp": datetime.now().isoformat()
        }
        _append_session_event(session_id, completion_event)

        # 更新会话状态
        _set_session_value(session_id, "execution_complete", True)
        _set_session_value(session_id, "status", TaskStatus.completed)
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
        _append_session_event(session_id, error_event)

        # 更新会话状态
        _set_session_value(session_id, "execution_complete", True)
        _set_session_value(session_id, "execution_error", str(e))
        _set_session_value(session_id, "status", TaskStatus.failed)
        _set_stream_state(session_id, "completed")


async def _resume_graph_execution(session_id: str, state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Resume graph execution with restored state (simplified version)

    Args:
        session_id: Session identifier
        state: Current state dictionary

    Returns:
        Response with stream URL for resuming execution
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

    # Retrieve or create checkpointer for this session
    checkpointer = _session_checkpointer.get(session_id)
    if not checkpointer:
        logger.warning(f"[Planning API] No checkpointer found for session {session_id}, creating new one")
        checkpointer = MemorySaver()
        _session_checkpointer[session_id] = checkpointer

    # Update session state
    with _sessions_lock:
        if session_id in _sessions:
            _sessions[session_id]["initial_state"] = state
            _sessions[session_id]["current_layer"] = current_layer
            _sessions[session_id]["events"] = []
            _sessions[session_id]["execution_complete"] = False
            _sessions[session_id]["execution_error"] = None
            _sessions[session_id]["status"] = TaskStatus.running
            # Preserve sent_layer_events to prevent re-sending completed layer events
            # This set tracks which layer completion events have already been sent
            if "sent_layer_events" not in _sessions[session_id]:
                _sessions[session_id]["sent_layer_events"] = set()
                logger.info(f"[Planning API] [{session_id}] 初始化 sent_layer_events")
            else:
                logger.info(f"[Planning API] [{session_id}] 保留 sent_layer_events: {_sessions[session_id]['sent_layer_events']}")

    # Create graph
    graph = create_village_planning_graph(checkpointer=checkpointer)

    # Reset stream state
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

        # Initialize session with events list
        with _sessions_lock:
            _sessions[session_id] = {
                "session_id": session_id,
                "project_name": request.project_name,
                "status": TaskStatus.running,
                "created_at": datetime.now().isoformat(),
                "request": request.dict(),
                "current_layer": 1,
                "initial_state": initial_state,
                "events": deque(maxlen=MAX_SESSION_EVENTS),  # Auto-limit to prevent OOM
                "execution_complete": False,
                "execution_error": None,
                "sent_layer_events": set(),  # Track sent layer completion events to prevent duplicates
            }

        # Mark execution as active
        _set_execution_active(session_id, True)

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
    SSE stream for planning progress (simplified version)

    Reads events from _sessions[session_id]["events"] list.

    Event Types:
    - connected: Connection established
    - layer_completed: Layer finished successfully
    - pause: Execution paused (step mode)
    - stream_paused: Stream paused, waiting for resume
    - completed: Planning finished
    - error: Execution error
    """
    if session_id not in _sessions:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    logger.info(f"[Planning API] [{session_id}] ===== SSE 连接建立 =====")
    logger.info(f"[Planning API] [{session_id}] 客户端端点: /api/planning/stream/{session_id}")

    async def event_generator():
        try:
            # 立即发送连接成功事件
            yield _format_sse_json({
                "type": "connected",
                "session_id": session_id,
                "timestamp": datetime.now().isoformat()
            })
            logger.info(f"[Planning API] [{session_id}] 已发送 'connected' 事件到客户端")

            event_index = 0  # 追踪已发送的事件索引

            while True:
                # 检查会话是否被删除
                if session_id not in _sessions:
                    logger.warning(f"[Planning] Session {session_id} deleted, closing stream")
                    break

                events_list = _get_session_events_copy(session_id)

                # 发送新事件
                while event_index < len(events_list):
                    event = events_list[event_index]
                    event_type = event.get("type")

                    # ✅ 关键修改：先发送所有非 stream_paused 的事件
                    if event_type == "stream_paused":
                        # 检查是否还有未发送的事件
                        if event_index + 1 < len(events_list):
                            logger.warning(f"[Planning API] [{session_id}] 发现 stream_paused，但后面还有事件，先发送其他事件")
                            # 暂时不发送 stream_paused，跳过它，先发送后面的
                            event_index += 1
                            continue
                        else:
                            # 确认这是最后一个事件了，可以安全关闭
                            logger.info(f"[Planning API] [{session_id}] 发送事件: {event_type}")
                            yield _format_sse_json(event)
                            event_index += 1

                            logger.info(f"[Planning API] [{session_id}] 流暂停，等待客户端恢复")
                            _stream_states[session_id] = "paused"
                            return
                    else:
                        # 正常发送其他事件（layer_completed, pause 等）
                        logger.info(f"[Planning API] [{session_id}] 发送事件: {event_type}")

                        # ✅ 额外日志：记录 layer_completed 事件详情
                        if event_type == "layer_completed":
                            logger.info(f"[Planning API] [{session_id}] → layer: {event.get('layer')}")
                            logger.info(f"[Planning API] [{session_id}] → report_content长度: {len(event.get('report_content', ''))}")
                            logger.info(f"[Planning API] [{session_id}] → dimension_reports数量: {len(event.get('dimension_reports', {}))}")

                        yield _format_sse_json(event)
                        event_index += 1

                        # 检查是否完成或出错
                        if event_type in ["completed", "error"]:
                            logger.info(f"[Planning API] [{session_id}] 流结束，原因: {event_type}")
                            return

                # 发送心跳（每秒）
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
        session = _get_session_value(session_id, None)
        if not session:
            raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

        initial_state = session.get("initial_state", {})
        review_id = initial_state.get("review_id", "")

        # 支持两种暂停模式：Step Mode (pause_after_step) 和 Review Mode (waiting_for_review)
        is_pause_mode = initial_state.get("pause_after_step", False)
        is_review_mode = initial_state.get("waiting_for_review", False)

        if not review_id and not is_pause_mode and request.action != "rollback":
            raise HTTPException(status_code=400, detail="No pending review or pause")

        from src.tools.web_review_tool import WebReviewTool
        web_review_tool = WebReviewTool()

        if request.action == "approve":
            # ✅ 添加：详细日志记录批准前的状态
            logger.info(f"[Planning API] [{session_id}] 批准请求 - 状态检查")
            logger.info(f"[Planning API] [{session_id}]   - review_id: {review_id}")
            logger.info(f"[Planning API] [{session_id}]   - pause_after_step: {is_pause_mode}")
            logger.info(f"[Planning API] [{session_id}]   - waiting_for_review: {is_review_mode}")
            logger.info(f"[Planning API] [{session_id}]   - current_layer: {initial_state.get('current_layer', 1)}")

            # 重置流状态为 active
            _stream_states[session_id] = "active"
            logger.info(f"[Planning API] Stream state reset to 'active' for session {session_id}")

            # ✅ 添加：检查是否有正在运行的后台执行
            if session_id in _active_executions and _active_executions[session_id]:
                logger.warning(f"[Planning API] [{session_id}] 检测到正在运行的后台执行，标记为取消")

            # 清除两种暂停标志
            initial_state["waiting_for_review"] = False
            initial_state["pause_after_step"] = False
            initial_state["human_feedback"] = ""
            initial_state["__interrupt__"] = False  # Clear interruption flag
            session["status"] = TaskStatus.running

            # ✅ 添加：清除pause事件追踪，为下一layer做准备
            if "sent_pause_events" in _sessions[session_id]:
                logger.info(f"[Planning API] [{session_id}] 清除pause事件追踪: {_sessions[session_id]['sent_pause_events']}")
                # 保留已完成的layer事件，但准备接收新layer的pause事件
                # 不清除整个set，只允许新的layer key

            # ✅ Fix: Update current_layer to next layer based on completion status
            current_layer = initial_state.get("current_layer", 1)
            if current_layer == 1 and initial_state.get("layer_1_completed", False):
                initial_state["current_layer"] = 2
                logger.info(f"[Planning API] [{session_id}] Layer 1完成，进入Layer 2")
            elif current_layer == 2 and initial_state.get("layer_2_completed", False):
                initial_state["current_layer"] = 3
                logger.info(f"[Planning API] [{session_id}] Layer 2完成，进入Layer 3")
            elif current_layer == 3 and initial_state.get("layer_3_completed", False):
                # Layer 3 is complete, move to final
                initial_state["current_layer"] = 4
                logger.info(f"[Planning API] [{session_id}] Layer 3完成，进入最终阶段")

            # Log which mode is being approved
            if is_pause_mode:
                logger.info(f"[Planning API] Approving in step mode (pause_after_step=True)")
            elif is_review_mode:
                logger.info(f"[Planning API] Approving in review mode (waiting_for_review=True)")

            if review_id:
                web_review_tool.submit_review_decision(review_id=review_id, action="approve")

            logger.info(f"[Planning API] Review approved, resuming session {session_id}")

            # Trigger graph re-invocation
            return await _resume_graph_execution(session_id, initial_state)

        elif request.action == "reject":
            initial_state["waiting_for_review"] = False
            initial_state["pause_after_step"] = False
            initial_state["human_feedback"] = request.feedback
            initial_state["need_revision"] = True
            initial_state["revision_target_dimensions"] = request.dimensions
            initial_state["__interrupt__"] = False  # Clear interruption flag
            session["status"] = TaskStatus.revising

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
        session = _get_session_value(session_id, None)
        if not session:
            raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

        project_name = session.get("project_name", "")

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

        return SessionStatusResponse(
            session_id=session_id,
            status=session.get("status", TaskStatus.pending),
            current_layer=current_layer,
            created_at=session.get("created_at", ""),
            checkpoints=checkpoints,
            checkpoint_count=len(checkpoints),
            progress=progress
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

        with _sessions_lock:
            _sessions[session_id] = {
                "session_id": session_id,
                "project_name": request.project_name,
                "status": TaskStatus.running,
                "created_at": datetime.now().isoformat(),
                "resumed_from": request.checkpoint_id,
                "current_layer": metadata.get("layer", 1),
                "initial_state": state,
                "events": deque(maxlen=MAX_SESSION_EVENTS),  # Auto-limit to prevent OOM
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
# Legacy Compatibility Layer
# ============================================

@router.post("/api/tasks")
async def create_task_legacy(request: StartPlanningRequest):
    """Legacy task creation endpoint (maps to start_planning)"""
    result = await start_planning(request, BackgroundTasks())
    return {
        "task_id": result["task_id"],
        "status": result["status"],
        "message": result["message"]
    }


@router.get("/api/tasks/{task_id}/stream")
async def stream_task_legacy(task_id: str):
    """Legacy task streaming endpoint (maps to stream_planning)"""
    return await stream_planning(task_id)


__all__ = ["router"]
