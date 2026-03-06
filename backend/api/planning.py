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
import threading
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

from src.core.config import (
    DEFAULT_TASK_DESCRIPTION,
    DEFAULT_CONSTRAINTS,
    DEFAULT_ENABLE_REVIEW,
    DEFAULT_STREAM_MODE,
    DEFAULT_STEP_MODE,
)

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from backend.api.tool_manager import tool_manager
from backend.schemas import TaskStatus
from backend.services.rate_limiter import rate_limiter
from backend.utils.progress_helper import calculate_progress
from backend.utils.logging import _extract_session_id
from src.orchestration.main_graph import create_village_planning_graph
from src.utils.output_manager import create_output_manager
from src.utils.paths import get_results_dir

# ✅ 导入异步数据库操作
from backend.database.operations_async import (
    add_session_event_async as add_event_async,
    get_session_events_async as get_events_async,
    create_planning_session_async as create_session_async,
    get_planning_session_async as get_session_async,
    update_planning_session_async as update_session_async,
    # UI 消息存储操作
    create_ui_message_async,
    get_ui_messages_async,
)
# ✅ 从 engine 导入数据库路径函数
from backend.database.engine import get_db_path

router = APIRouter()

logger = logging.getLogger(__name__)

# ============================================
# Global Checkpointer Management
# ============================================

_checkpointer: Optional[Any] = None
_checkpointer_lock = asyncio.Lock()
_checkpointer_initialized = False


async def get_global_checkpointer() -> Any:
    """
    获取全局 AsyncSqliteSaver 实例（单例模式）

    使用单例模式避免重复创建连接和调用 setup()，提高性能。
    此函数在第一次调用时初始化 checkpointer，后续调用返回同一实例。

    Returns:
        AsyncSqliteSaver 实例

    Raises:
        Exception: 如果初始化失败
    """
    global _checkpointer, _checkpointer_initialized

    # 快速路径：如果已初始化，直接返回
    if _checkpointer is not None and _checkpointer_initialized:
        return _checkpointer

    # 慢速路径：需要初始化（带锁）
    async with _checkpointer_lock:
        # 双重检查：可能在等待锁时已被其他协程初始化
        if _checkpointer is not None and _checkpointer_initialized:
            return _checkpointer

        try:
            logger.info("[Checkpointer] 正在初始化全局 AsyncSqliteSaver 实例...")

            import aiosqlite
            from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

            # 创建连接
            conn = await aiosqlite.connect(get_db_path(), check_same_thread=False)
            
            # 启用 WAL 模式以提高并发写入安全性
            await conn.execute("PRAGMA journal_mode=WAL")
            await conn.execute("PRAGMA synchronous=NORMAL")
            await conn.execute("PRAGMA cache_size=-64000")  # 64MB cache
            logger.info("[Checkpointer] WAL mode enabled")
            
            _checkpointer = AsyncSqliteSaver(conn)

            # 初始化表结构（只在第一次时调用）
            await _checkpointer.setup()

            _checkpointer_initialized = True
            logger.info("[Checkpointer] ✅ 全局 AsyncSqliteSaver 实例初始化成功")

            return _checkpointer

        except Exception as e:
            logger.error(f"[Checkpointer] ❌ 初始化失败: {e}", exc_info=True)
            raise


# Configuration constants
MAX_SESSION_EVENTS = 1000  # Maximum events to keep per session (约 30 分钟流式事件)
EVENT_CLEANUP_INTERVAL_SECONDS = 300  # Cleanup interval: 5 minutes (instead of 1 hour)

# In-memory session storage (for production: use Redis)
_sessions: Dict[str, Dict[str, Any]] = {}
# Track active executions to prevent duplicate runs
_active_executions: Dict[str, bool] = {}
# Track stream states to prevent infinite reconnection
_stream_states: Dict[str, str] = {}  # session_id -> "active" | "paused" | "completed"

# Status query log optimization - track repeated queries to reduce log spam
_status_log_tracker: Dict[str, Dict[str, Any]] = {}  # session_id -> {count, last_state, last_log_time}
_status_log_lock = Lock()

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
    role: str = Field(..., description="Message role: user | assistant | system")
    content: str = Field(..., description="Message content")
    message_type: str = Field(default="text", description="Message type: text | file | progress | layer_completed | dimension_report")
    metadata: Optional[Dict[str, Any]] = Field(default=None, description="Additional message metadata")


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


# ============================================
# ✅ 新增：异步版本的事件追加函数
# ============================================

async def _append_session_event_async(session_id: str, event: Dict) -> bool:
    """
    异步版本的会话事件追加（高性能）

    使用异步数据库操作替代内存操作，
    显著提升高并发场景下的性能。

    Args:
        session_id: Session identifier
        event: Event dictionary to append

    Returns:
        True: 成功, False: 失败
    """
    try:
        # 使用异步数据库包装器
        success = await add_event_async(session_id, event)
        if success:
            logger.debug(f"[Async DB] Event appended to session {session_id}")
            # 同时更新内存缓存（保持兼容性）
            _append_session_event(session_id, event)
        return success
    except Exception as e:
        logger.error(f"[Async DB] Failed to append event: {e}", exc_info=True)
        # 失败时回退到内存版本
        _append_session_event(session_id, event)
        return False


def append_dimension_complete_event(
    session_id: str,
    layer: int,
    dimension_key: str,
    dimension_name: str,
    content: str
) -> None:
    """
    发送维度完成事件到 SSE 队列
    
    这是一个同步函数，供子图节点在维度分析完成后调用。
    
    Args:
        session_id: 会话ID
        layer: 层级编号 (1/2/3)
        dimension_key: 维度键名
        dimension_name: 维度显示名称
        content: 维度分析内容
    """
    event_data = {
        "type": "dimension_complete",
        "layer": layer,
        "dimension_key": dimension_key,
        "dimension_name": dimension_name,
        "full_content": content,
        "timestamp": datetime.now().isoformat()
    }
    _append_session_event(session_id, event_data)
    logger.debug(f"[Dimension Event] Layer {layer} - {dimension_name} completed ({len(content)} chars)")


# ==========================================
# Token 级流式输出 - 频率控制状态
# ==========================================
_dimension_delta_last_sent: Dict[str, float] = {}  # dimension_key -> last_sent_timestamp
_dimension_delta_token_count: Dict[str, int] = {}  # dimension_key -> token_count_since_last_send
_dimension_delta_lock = threading.Lock()

# 频率控制参数
DELTA_MIN_INTERVAL_MS = 50  # 最小发送间隔（毫秒）
DELTA_MIN_TOKENS = 5  # 最小 token 数量


def append_dimension_delta_event(
    session_id: str,
    layer: int,
    dimension_key: str,
    dimension_name: str,
    delta: str,
    accumulated: str
) -> bool:
    """
    发送维度增量事件到 SSE 队列（带频率控制）
    
    频率控制策略：
    - 每 50ms 最多发送一次
    - 或每累积 5 个 tokens 发送一次
    
    这是一个同步函数，供子图节点的 token 回调调用。
    
    Args:
        session_id: 会话ID
        layer: 层级编号 (1/2/3)
        dimension_key: 维度键名
        dimension_name: 维度显示名称
        delta: 增量文本（单个 token）
        accumulated: 累积文本
    
    Returns:
        bool: 是否实际发送了事件（用于调试）
    """
    current_time = time.time() * 1000  # 转换为毫秒
    cache_key = f"{session_id}:{layer}:{dimension_key}"
    
    with _dimension_delta_lock:
        # 检查是否应该发送
        last_sent = _dimension_delta_last_sent.get(cache_key, 0)
        token_count = _dimension_delta_token_count.get(cache_key, 0) + 1
        
        time_elapsed = current_time - last_sent
        should_send = (time_elapsed >= DELTA_MIN_INTERVAL_MS) or (token_count >= DELTA_MIN_TOKENS)
        
        if not should_send:
            # 只更新计数，不发送
            _dimension_delta_token_count[cache_key] = token_count
            return False
        
        # 发送事件
        event_data = {
            "type": "dimension_delta",
            "layer": layer,
            "dimension_key": dimension_key,
            "dimension_name": dimension_name,
            "delta": delta,
            "accumulated": accumulated,
            "timestamp": datetime.now().isoformat()
        }
        _append_session_event(session_id, event_data)
        
        # 更新状态
        _dimension_delta_last_sent[cache_key] = current_time
        _dimension_delta_token_count[cache_key] = 0
        
        return True


def reset_dimension_delta_state(session_id: str, layer: int, dimension_key: str) -> None:
    """
    重置维度增量状态（在维度开始时调用）
    
    Args:
        session_id: 会话ID
        layer: 层级编号
        dimension_key: 维度键名
    """
    cache_key = f"{session_id}:{layer}:{dimension_key}"
    with _dimension_delta_lock:
        _dimension_delta_last_sent.pop(cache_key, None)
        _dimension_delta_token_count.pop(cache_key, None)


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
        # Need Layer 1 data (analysis_reports)
        return bool(state.get("analysis_reports"))
    elif current_layer == 3:
        # Need Layer 1 and 2 data (analysis_reports, concept_reports)
        return bool(
            state.get("analysis_reports") and
            state.get("concept_reports")
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
        "previous_layer": 0,  # 0 表示无已完成的层级
        "layer_1_completed": False,
        "layer_2_completed": False,
        "layer_3_completed": False,

        # Review settings
        "need_human_review": enable_review_effective,
        "human_feedback": None,
        "need_revision": False,

        # Layer outputs (统一命名)
        "analysis_reports": {},    # Layer 1 维度报告
        "concept_reports": {},     # Layer 2 维度报告
        "detail_reports": {},      # Layer 3 维度报告
        "final_output": "",

        # Output management - use serializable path string
        "output_path": str(output_manager.output_path),

        # Checkpoint configuration
        "checkpoint_enabled": True,
        "last_checkpoint_id": "",

        # Step mode settings
        "step_mode": request.step_mode,
        "step_level": "layer",
        "pause_after_step": False,

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

        # 创建 Token 回调工厂，用于实时发送维度内容到 SSE
        dimension_accumulators = {}  # 跟踪每个维度的累积内容

        def token_callback_factory(layer: int, dimension: str):
            """创建 Token 回调函数，将维度内容实时发送到 SSE"""
            def on_token(token: str, accumulated: str):
                # 更新累积内容
                accumulator_key = f"{layer}_{dimension}"
                dimension_accumulators[accumulator_key] = accumulated

                # 发送维度增量事件
                event_data = {
                    "type": "dimension_delta",
                    "layer": layer,
                    "dimension_key": dimension,
                    "delta": token,
                    "accumulated": accumulated,
                    "timestamp": datetime.now().isoformat()
                }
                _append_session_event(session_id, event_data)

            return on_token

        # ✅ 将 token 回调工厂放入 config（不污染状态，避免序列化问题）
        # 修复: initial_state 可能为 None（从 Checkpoint 恢复时），需要空值保护
        if initial_state and initial_state.get("_streaming_enabled", False):
            config["configurable"]["_token_callback_factory"] = token_callback_factory
            logger.info(f"[Planning] [{session_id}] Token 回调工厂已放入 config")

        # 定义运行时专用的key（不应持久化到checkpoint）
        RUNTIME_KEYS = {
            "_streaming_queue",
            "_storage_pipeline",
            "_dimension_events",
            "_token_callback_factory",  # ✅ 保留此行，防止状态污染
            "_streaming_enabled",
            "_pending_tokens",
        }

        # 清理运行时对象，避免 msgpack 序列化错误
        # 修复: initial_state 可能为 None，使用空字典作为默认值
        clean_state = {k: v for k, v in (initial_state or {}).items() if k not in RUNTIME_KEYS}
        logger.info(f"[Planning] [{session_id}] 已清理运行时对象，传递给 LangGraph 的状态键: {list(clean_state.keys())}")

        # 流式执行图
        logger.info(f"[Planning] [{session_id}] 开始流式执行 graph.astream()")
        stream_iterator = graph.astream(clean_state, config, stream_mode="values")

        previous_event = {}
        sent_layer_started = set()  # 追踪已发送的 layer_started 事件
        async for event in stream_iterator:
            # ✅ 检测层级开始（layer_started 事件）
            # 修复：步进模式下，刚完成层级时跳过 layer_started（等待恢复时再发送）
            current_layer = event.get("current_layer")
            pause_after_step = event.get("pause_after_step", False)
            previous_layer = event.get("previous_layer", 0)
            step_mode = event.get("step_mode", False)
            
            # 步进模式下，刚完成层级时跳过 layer_started（等待恢复）
            # previous_layer > 0 表示刚完成一个层级，此时应该暂停等待审查
            skip_layer_started = previous_layer > 0 and step_mode
            
            if skip_layer_started:
                logger.info(f"[Planning] [{session_id}] 步进模式：跳过 layer_started 发送（previous_layer={previous_layer}，等待恢复）")
            elif current_layer and current_layer in [1, 2, 3] and not pause_after_step:
                layer_started_key = f"layer_{current_layer}_started"
                if layer_started_key not in sent_layer_started:
                    # 发送 layer_started 事件
                    layer_names = {1: "现状分析", 2: "规划思路", 3: "详细规划"}
                    started_event = {
                        "type": "layer_started",
                        "layer": current_layer,
                        "layer_number": current_layer,
                        "layer_name": layer_names.get(current_layer, f"Layer {current_layer}"),
                        "session_id": session_id,
                        "message": f"开始执行 Layer {current_layer}: {layer_names.get(current_layer, '')}",
                        "timestamp": datetime.now().isoformat()
                    }
                    await _append_session_event_async(session_id, started_event)
                    sent_layer_started.add(layer_started_key)
                    logger.info(f"[Planning] [{session_id}] ✓ layer_started 事件已发送: Layer {current_layer}")

            # 检测层级完成
            for layer_num in [1, 2, 3]:
                now_completed = event.get(f"layer_{layer_num}_completed", False)

                # ✅ 简化：只检查层级是否完成，不依赖 previous_event
                if now_completed:
                    # 事件key用于去重追踪
                    event_key = f"layer_{layer_num}_completed"

                    # 检查：未发送过
                    if event_key not in sent_events:
                        # 获取维度报告内容（使用新的统一命名）
                        from src.utils.report_utils import (
                            generate_analysis_report,
                            generate_concept_report,
                            generate_detail_report
                        )
                        
                        project_name = event.get("project_name", "村庄")
                        
                        if layer_num == 1:
                            dimension_reports = event.get("analysis_reports", {})
                            report = generate_analysis_report(dimension_reports, project_name)
                        elif layer_num == 2:
                            dimension_reports = event.get("concept_reports", {})
                            report = generate_concept_report(dimension_reports, project_name)
                            # ✅ 添加 Layer 2 专用调试日志
                            logger.info(f"[Planning] [{session_id}] === Layer 2 完成 ===")
                            logger.info(f"[Planning] [{session_id}] event keys: {list(event.keys())}")
                            logger.info(f"[Planning] [{session_id}] concept_reports: {dimension_reports}")
                            logger.info(f"[Planning] [{session_id}] dimension_reports keys: {list(dimension_reports.keys())}")
                            if dimension_reports:
                                for key, value in dimension_reports.items():
                                    logger.info(f"[Planning] [{session_id}]   - {key}: {len(value)} chars")
                        else:  # layer_num == 3
                            dimension_reports = event.get("detail_reports", {})
                            report = generate_detail_report(dimension_reports, project_name)
                            # ✅ 添加 Layer 3 专用调试日志
                            logger.info(f"[Planning] [{session_id}] === Layer 3 完成 ===")
                            logger.info(f"[Planning] [{session_id}] event keys: {list(event.keys())}")
                            logger.info(f"[Planning] [{session_id}] detail_reports: {dimension_reports}")
                            logger.info(f"[Planning] [{session_id}] dimension_reports keys: {list(dimension_reports.keys())}")
                            if dimension_reports:
                                for key, value in dimension_reports.items():
                                    logger.info(f"[Planning] [{session_id}]   - {key}: {len(value)} chars")

                        # 生成事件并添加到会话事件列表
                        event_data = {
                            "type": "layer_completed",
                            "layer": layer_num,
                            "layer_number": layer_num,
                            "session_id": session_id,
                            "message": f"Layer {layer_num} completed",
                            "report_content": report[:500000],  # Truncate if too large
                            "dimension_reports": dimension_reports,
                            "pause_after_step": event.get("pause_after_step", False),
                            "previous_layer": event.get("previous_layer", 0),  # 刚完成的层级
                            "timestamp": datetime.now().isoformat()
                        }
                        # 使用异步版本（高性能）
                        await _append_session_event_async(session_id, event_data)
                        sent_events.add(event_key)  # 标记已发送
                        _set_session_value(session_id, "sent_layer_events", sent_events)  # 保存回session
                        logger.info(f"[Planning] [{session_id}] ✓ layer_completed 事件已添加到队列")
                        logger.info(f"[Planning] [{session_id}]   - Layer {layer_num}")
                        logger.info(f"[Planning] [{session_id}]   - 队列长度: {len(events_list)}")
                        logger.info(f"[Planning] [{session_id}]   - 报告长度: {len(report)} 字符")
                        logger.info(f"[Planning] [{session_id}]   - 维度报告数量: {len(dimension_reports)}")
                        logger.info(f"[Planning] [{session_id}]   - pause_after_step: {event.get('pause_after_step', False)}")
                        logger.info(f"[Planning] [{session_id}]   - previous_layer: {event.get('previous_layer', 0)}")
                        logger.info(f"[Planning] [{session_id}]   - 已发送事件: {sent_events}")
                        # sent_layer_events 和 sent_pause_events 是内存状态,不需要持久化到数据库
                    else:
                        # 重复事件检测
                        logger.info(f"[Planning] [{session_id}] ⚠️ 跳过重复的 layer_{layer_num}_completed 事件")
                        logger.info(f"[Planning] [{session_id}]   - 事件已在已发送列表中: {sent_events}")

            # 【新增】检测修复完成事件
            last_revised_dimensions = event.get("last_revised_dimensions", [])
            if last_revised_dimensions and not event.get("need_revision", False):
                logger.info(f"[Planning] [{session_id}] === 检测到修复完成 ===")
                logger.info(f"[Planning] [{session_id}]   - last_revised_dimensions: {last_revised_dimensions}")
                
                # 获取已发送的 revised 事件集合（幂等检查）
                sent_revised_events = _get_session_value(session_id, "sent_revised_events", set())
                
                # 从修订历史获取最新条目
                revision_history = event.get("revision_history", [])
                
                for dim in last_revised_dimensions:
                    # 从历史记录中获取该维度的最新修订
                    latest_revision = next(
                        (r for r in reversed(revision_history) if r.get("dimension") == dim),
                        None
                    )
                    
                    if latest_revision:
                        layer = latest_revision.get("layer", 1)
                        # 使用复合键确保同一维度在不同层级可以独立修复
                        revised_event_key = f"revised_{layer}_{dim}"
                        
                        # 幂等检查：避免重复发送
                        if revised_event_key in sent_revised_events:
                            logger.debug(f"[Planning] [{session_id}] 跳过重复的 revised 事件: {revised_event_key}")
                            continue
                        
                        # 发送 dimension_revised SSE 事件
                        event_data = {
                            "type": "dimension_revised",
                            "dimension": dim,
                            "layer": layer,
                            "old_content": latest_revision.get("old_content", "")[:1000],  # 截断避免过大
                            "new_content": latest_revision.get("new_content", ""),
                            "feedback": latest_revision.get("feedback", "")[:500],  # 截断
                            "timestamp": latest_revision.get("timestamp", datetime.now().isoformat())
                        }
                        await _append_session_event_async(session_id, event_data)
                        
                        # 标记为已发送
                        sent_revised_events.add(revised_event_key)
                        _set_session_value(session_id, "sent_revised_events", sent_revised_events)
                        logger.info(f"[Planning] [{session_id}] ✓ dimension_revised 事件已发送: {dim}")
                
                # 清除标志避免重复检测（通过更新内存状态）
                # 注意：不能直接修改 event，但下次循环会检测新的状态

            # 精简：不再手动同步数据库字段
            # AsyncSqliteSaver 会自动将完整状态保存到 checkpoints 表
            # 我们只需要维护业务元数据（status, created_at 等）
            
            with _sessions_lock:
                if session_id in _sessions:
                    # 更新内存中的状态
                    _sessions[session_id]["initial_state"].update(event)
                    _sessions[session_id]["current_layer"] = event.get("current_layer", 1)
                    
                    # 将关键字段也同步到 session_state 根级别
                    # 这样 /api/planning/status 端点可以正确读取这些字段
                    if "pause_after_step" in event:
                        _sessions[session_id]["pause_after_step"] = event["pause_after_step"]
                    if "previous_layer" in event:
                        _sessions[session_id]["previous_layer"] = event["previous_layer"]

            # 检查暂停状态（步进模式）
            if event.get("pause_after_step"):
                logger.info(f"[Planning] [{session_id}] 检测到暂停状态")
                logger.info(f"[Planning] [{session_id}]   - pause_after_step: {event.get('pause_after_step')}")
                logger.info(f"[Planning] [{session_id}]   - previous_layer: {event.get('previous_layer')}")
                
                # 使用 previous_layer 作为待审查层级
                previous_layer = event.get("previous_layer", 1)

                # pause事件去重
                pause_event_key = f"pause_layer_{previous_layer}"

                if pause_event_key not in sent_pause_events:
                    # 首次检测到此layer的暂停，添加事件
                    pause_event = {
                        "type": "pause",
                        "session_id": session_id,
                        "current_layer": previous_layer,  # 刚完成的层级
                        "checkpoint_id": event.get("last_checkpoint_id", ""),
                        "reason": "step_mode",
                        "timestamp": datetime.now().isoformat()
                    }
                    _append_session_event(session_id, pause_event)
                    sent_pause_events.add(pause_event_key)
                    _set_session_value(session_id, "sent_pause_events", sent_pause_events)
                    # sent_pause_events 是内存状态,不需要持久化到数据库
                    
                    # 更新会话状态为 paused
                    _set_session_value(session_id, "status", TaskStatus.paused)
                    logger.info(f"[Planning] [{session_id}] 状态已更新为 paused")
                    
                    # 持久化状态到数据库
                    try:
                        await update_session_async(session_id, {
                            "status": TaskStatus.paused,
                        })
                        logger.info(f"[Planning] [{session_id}] 状态已持久化到数据库")
                    except Exception as e:
                        logger.error(f"[Planning] [{session_id}] 持久化状态失败: {e}")

                    stream_paused_event = {
                        "type": "stream_paused",
                        "session_id": session_id,
                        "current_layer": previous_layer,  # ✅ 使用刚刚完成的层级
                        "reason": "waiting_for_resume",
                        "timestamp": datetime.now().isoformat()
                    }
                    # 使用异步版本添加事件
                    # SSE generator 会在发送 stream_paused 后自动结束流
                    await _append_session_event_async(session_id, stream_paused_event)

                    _stream_states[session_id] = "paused"
                    logger.info(f"[Planning] [{session_id}]   - 已发送pause事件: {sent_pause_events}")
                else:
                    # ⚠️ 重复pause事件，跳过
                    logger.info(f"[Planning] [{session_id}] ⚠️ 跳过重复的pause事件 (Layer {previous_layer})")
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
        # ✅ 使用异步版本
        await _append_session_event_async(session_id, completion_event)

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
        # ✅ 使用异步版本
        await _append_session_event_async(session_id, error_event)

        # 更新会话状态
        _set_session_value(session_id, "execution_complete", True)
        _set_session_value(session_id, "execution_error", str(e))
        _set_session_value(session_id, "status", TaskStatus.failed)
        _set_stream_state(session_id, "completed")


async def _resume_graph_execution(session_id: str, state: Dict[str, Any] = None) -> Dict[str, Any]:
    """
    Resume graph execution from checkpoint
    
    LangGraph 官方推荐模式：
    1. Checkpoint 是唯一的数据源（Single Source of Truth）
    2. 使用 graph.astream(None, config) 恢复执行
    3. 废弃内存状态验证，信任 Checkpoint 完整性

    Args:
        session_id: Session identifier
        state: (已废弃) 保留参数用于兼容旧调用

    Returns:
        Response with stream URL for resuming execution
    """
    # ✅ 使用统一的单例获取方式
    saver = await get_global_checkpointer()
    graph = create_village_planning_graph(checkpointer=saver)
    config = {"configurable": {"thread_id": session_id}}
    
    # ✅ 从 Checkpoint 获取完整状态（包含所有层级 reports）
    checkpoint_state = await graph.aget_state(config)
    if not checkpoint_state or not checkpoint_state.values:
        logger.error(f"[Planning API] [{session_id}] Checkpoint 中未找到会话状态")
        raise HTTPException(
            status_code=400,
            detail=f"Session {session_id} not found in checkpoint"
        )
    
    # 从 Checkpoint 获取完整状态
    full_state = checkpoint_state.values
    current_layer = full_state.get("current_layer", 1)
    
    logger.info(f"[Planning API] [{session_id}] 从 Checkpoint 恢复完整状态:")
    logger.info(f"[Planning API] [{session_id}]   - current_layer: {current_layer}")
    logger.info(f"[Planning API] [{session_id}]   - analysis_reports: {len(full_state.get('analysis_reports', {}))} 个维度")
    logger.info(f"[Planning API] [{session_id}]   - concept_reports: {len(full_state.get('concept_reports', {}))} 个维度")
    logger.info(f"[Planning API] [{session_id}]   - detail_reports: {len(full_state.get('detail_reports', {}))} 个维度")
    logger.info(f"[Planning API] [{session_id}]   - need_revision: {full_state.get('need_revision', False)}")

    # Update session state（仅更新业务元数据，不覆盖 Checkpoint 数据）
    with _sessions_lock:
        if session_id in _sessions:
            # 同步 current_layer 到内存会话
            _sessions[session_id]["current_layer"] = current_layer
            _sessions[session_id]["execution_complete"] = False
            _sessions[session_id]["execution_error"] = None
            _sessions[session_id]["status"] = TaskStatus.running
            # Preserve sent_layer_events to prevent re-sending completed layer events
            if "sent_layer_events" not in _sessions[session_id]:
                _sessions[session_id]["sent_layer_events"] = set()
                logger.info(f"[Planning API] [{session_id}] 初始化 sent_layer_events")
            else:
                logger.info(f"[Planning API] [{session_id}] 保留 sent_layer_events: {_sessions[session_id]['sent_layer_events']}")
            # 初始化 sent_revised_events（如果不存在）
            if "sent_revised_events" not in _sessions[session_id]:
                _sessions[session_id]["sent_revised_events"] = set()
                logger.info(f"[Planning API] [{session_id}] 初始化 sent_revised_events")
            # ✅ 清空 sent_pause_events 以便下一层暂停
            _sessions[session_id]["sent_pause_events"].clear()
            
            # ✅ 关键修复：同步更新 initial_state 中的 pause_after_step
            # 这样 /api/planning/status 端点才能正确读取到 False
            _sessions[session_id]["initial_state"]["pause_after_step"] = False
            logger.info(f"[Planning API] [{session_id}] 已清除内存中的 pause_after_step 标志")

    # 添加 resumed 事件到 events 列表，通知前端已恢复执行
    _append_session_event(session_id, {
        "type": "resumed",
        "session_id": session_id,
        "current_layer": current_layer,
        "message": "Execution resumed after review approval",
        "timestamp": datetime.now().isoformat()
    })
    logger.info(f"[Planning API] [{session_id}] 已添加 resumed 事件")

    # ✅ 持久化状态到数据库:只更新业务元数据
    try:
        await update_session_async(session_id, {
            "status": TaskStatus.running,
            "execution_error": None,
        })
        logger.info(f"[Planning API] [{session_id}] 状态已持久化到数据库: status=running")
    except Exception as db_error:
        logger.error(f"[Planning API] [{session_id}] 持久化状态失败: {db_error}", exc_info=True)
        # 继续执行,不阻断恢复流程

    # ✅ 使用 graph.aupdate_state 清除暂停标志和 previous_layer（如果需要）
    # 同时清除 previous_layer，避免 init_pause_state 在恢复后重新设置 pause_after_step = True
    if full_state.get("pause_after_step", False):
        await graph.aupdate_state(
            config,
            {
                "pause_after_step": False,
                "previous_layer": 0,  # 清除 previous_layer，避免重复暂停
            }
        )
        logger.info(f"[Planning API] [{session_id}] 已清除 pause_after_step 和 previous_layer 标志")

    # Reset stream state
    _set_stream_state(session_id, "active")

    # ✅ 使用 None 作为输入，LangGraph 自动从 Checkpoint 加载完整状态
    asyncio.create_task(
        _execute_graph_in_background(session_id, graph, None, saver)
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
            rate_limiter.mark_task_completed(request.project_name, success=False)

            raise HTTPException(
                status_code=500,
                detail=f"Failed to create planning session in database: {str(db_error)}"
            )

        # Initialize in-memory session with events list (after DB commit)
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
                "sent_revised_events": set(),  # Track sent dimension revised events to prevent duplicates
                "sent_pause_events": set(),  # Track sent pause events to prevent duplicates
            }

        # Mark execution as active
        _set_execution_active(session_id, True)

        # 使用全局 checkpointer 单例
        saver = await get_global_checkpointer()

        logger.info(f"[Planning API] 创建 LangGraph 实例 (使用全局 AsyncSqliteSaver)")
        graph = create_village_planning_graph(checkpointer=saver)
        
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
    # 1. 内存未命中 → 尝试从数据库重建
    if session_id not in _sessions:
        rebuilt = await _rebuild_session_from_db(session_id)
        if not rebuilt:
            raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    logger.info(f"[Planning API] [{session_id}] ===== SSE 连接建立 =====")

    async def event_generator():
        try:
            # 立即发送连接成功事件
            yield _format_sse_json({
                "type": "connected",
                "session_id": session_id,
                "timestamp": datetime.now().isoformat()
            })

            event_index = 0

            while True:
                if session_id not in _sessions:
                    logger.warning(f"[Planning] Session {session_id} deleted, closing stream")
                    break

                events_list = _get_session_events_copy(session_id)

                while event_index < len(events_list):
                    event = events_list[event_index]
                    event_type = event.get("type")

                    # stream_paused 特殊处理：确保所有其他事件都处理完再关闭
                    if event_type == "stream_paused":
                        # 检查队列中是否还有其他未处理的事件（非 stream_paused 类型）
                        remaining_events = [
                            e for e in events_list[event_index:]
                            if e.get("type") != "stream_paused"
                        ]
                        if remaining_events:
                            # 还有其他事件要处理，跳过 stream_paused
                            logger.info(f"[Planning] [{session_id}] stream_paused: 还有 {len(remaining_events)} 个事件待处理，跳过")
                            event_index += 1
                            continue
                        else:
                            # 所有事件都处理完了，发送 stream_paused 并关闭连接
                            logger.info(f"[Planning] [{session_id}] stream_paused: 所有事件已处理，关闭连接")
                            yield _format_sse_json(event)
                            event_index += 1
                            _stream_states[session_id] = "paused"
                            return
                    else:
                        yield _format_sse_json(event)
                        event_index += 1

                        if event_type in ["completed", "error"]:
                            return

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


@router.get("/api/planning/status/{session_id}")
async def get_session_status(session_id: str):
    """
    Get session status (直接从内存和数据库读取，避免 checkpointer 的线程问题)
    获取会话状态 - 从数据库读取业务元数据,从内存状态获取实时进度

    Args:
        session_id: Session identifier

    Returns:
        SessionStatusResponse with current state
    """
    # 1. 从数据库获取业务元数据 (轻量级)
    db_session = await get_session_async(session_id)
    if not db_session:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    # 2. 从内存状态获取 current_layer 和其他状态信息（最快、最可靠）
    current_layer = 1
    previous_layer = 0  # 初始化默认值，防止 UnboundLocalError
    layer_1_completed = False
    layer_2_completed = False
    layer_3_completed = False
    pause_after_step = False
    execution_complete = False

    if session_id in _sessions:
        session_state = _sessions[session_id]
        initial_state = session_state.get("initial_state", {})
        
        current_layer = session_state.get("current_layer", 1)
        # 从已发送的事件推断层级完成状态
        sent_events = session_state.get("sent_layer_events", set())
        layer_1_completed = "layer_1_completed" in sent_events
        layer_2_completed = "layer_2_completed" in sent_events
        layer_3_completed = "layer_3_completed" in sent_events
        execution_complete = session_state.get("execution_complete", False)
        
        # 从 initial_state 读取暂停相关字段
        pause_after_step = initial_state.get("pause_after_step", False)
        previous_layer = initial_state.get("previous_layer", 0)

    # 3. 如果内存中没有，尝试从数据库获取
    if current_layer == 1:
        current_layer = db_session.get("current_layer", 1)
        # 从数据库恢复 previous_layer，如果没有则根据 current_layer 推算
        previous_layer = db_session.get("previous_layer", current_layer - 1 if current_layer > 1 else 0)
        layer_1_completed = db_session.get("layer_1_completed", False)
        layer_2_completed = db_session.get("layer_2_completed", False)
        layer_3_completed = db_session.get("layer_3_completed", False)
        execution_complete = db_session.get("execution_complete", False)

    # 4. 计算进度
    progress = None
    if current_layer == 4:
        progress = 100
    elif current_layer in [1, 2, 3]:
        progress = (current_layer / 3) * 100

    # 优化日志输出 - 状态变化时打印，或每 10 次查询汇总打印
    current_status = db_session.get("status", "running")
    state_key = f"{current_status}|{current_layer}|{pause_after_step}|{previous_layer}"
    
    with _status_log_lock:
        tracker = _status_log_tracker.get(session_id, {
            "count": 0, 
            "last_state": None, 
            "last_log_time": 0
        })
        tracker["count"] += 1
        state_changed = tracker["last_state"] != state_key
        time_since_last_log = time.time() - tracker["last_log_time"]
        
        # 打印日志的条件：状态变化 或 超过 30 秒未打印
        should_log = state_changed or time_since_last_log > 30
        
        if should_log:
            if state_changed:
                logger.info(f"[Status] [{session_id}] 状态变化: {tracker['last_state']} → {state_key} (查询次数: {tracker['count']})")
            else:
                logger.info(f"[Status] [{session_id}] 轮询汇总: {state_key} (查询次数: {tracker['count']})")
            
            # 重置计数器
            tracker["count"] = 0
            tracker["last_state"] = state_key
            tracker["last_log_time"] = time.time()
        
        _status_log_tracker[session_id] = tracker

    # 【新增】从 LangGraph Checkpoint 获取 messages 和 revision_history
    messages = []
    revision_history = []
    
    try:
        checkpointer = await get_global_checkpointer()
        graph = create_village_planning_graph(checkpointer=checkpointer)
        config = {"configurable": {"thread_id": session_id}}
        checkpoint_state = await graph.aget_state(config)
        
        if checkpoint_state and checkpoint_state.values:
            # 提取消息历史
            raw_messages = checkpoint_state.values.get("messages", [])
            # 将 BaseMessage 转换为可序列化的格式
            for msg in raw_messages:
                if hasattr(msg, 'content'):
                    messages.append({
                        "type": msg.__class__.__name__.lower().replace("message", ""),
                        "content": msg.content,
                        "role": "assistant" if "ai" in msg.__class__.__name__.lower() else "user"
                    })
            
            # 提取修订历史
            revision_history = checkpoint_state.values.get("revision_history", [])
            
            # 只在消息数量变化时打印日志（使用 DEBUG 级别）
            msg_count = len(messages)
            rev_count = len(revision_history)
            with _status_log_lock:
                last_msg_count = _status_log_tracker.get(session_id, {}).get("last_msg_count", -1)
                if msg_count != last_msg_count:
                    logger.debug(f"[Status] [{session_id}] 消息数: {msg_count}, 修订记录: {rev_count}")
                    if session_id in _status_log_tracker:
                        _status_log_tracker[session_id]["last_msg_count"] = msg_count
    except Exception as e:
        logger.warning(f"[Status] [{session_id}] 获取 Checkpoint 数据失败: {e}")
        # 继续执行，不影响其他状态返回

    return {
        "session_id": session_id,
        # 业务元数据 (来自数据库)
        "status": db_session.get("status", "running"),
        "execution_error": db_session.get("execution_error"),
        "created_at": db_session.get("created_at", ""),
        # 当前层级和状态 (来自内存或数据库)
        "current_layer": current_layer,
        "previous_layer": previous_layer if session_id in _sessions else db_session.get("previous_layer"),
        "layer_1_completed": layer_1_completed,
        "layer_2_completed": layer_2_completed,
        "layer_3_completed": layer_3_completed,
        "pause_after_step": pause_after_step,
        "execution_complete": execution_complete,
        # 进度
        "progress": progress,
        "last_checkpoint_id": None,
        # 【新增】消息历史和修订历史
        "messages": messages,
        "revision_history": revision_history,
        # 【新增】UI 消息列表（从数据库加载）
        "ui_messages": await get_ui_messages_async(session_id),
    }


@router.post("/api/planning/messages/{session_id}")
async def create_ui_message(session_id: str, request: CreateUIMessageRequest):
    """
    存储 UI 消息到数据库
    
    Args:
        session_id: Session identifier
        request: Message data
        
    Returns:
        Created message ID
    """
    # 验证 session 存在
    db_session = await get_session_async(session_id)
    if not db_session:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")
    
    try:
        message_id = await create_ui_message_async(
            session_id=session_id,
            role=request.role,
            content=request.content,
            message_type=request.message_type,
            metadata=request.metadata
        )
        return {"success": True, "message_id": message_id}
    except Exception as e:
        logger.error(f"[Planning API] Failed to create UI message: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to create message: {str(e)}")


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


@router.post("/api/planning/review/{session_id}")
async def review_action(session_id: str, request: ReviewActionRequest):
    """
    Handle review actions from web frontend
    支持内存未命中时从数据库重建会话
    """
    logger.info(f"🔥🔥🔥 review_action 被调用！ session_id={session_id}")  # 新增
    try:
        # ========== 1. 尝试从内存获取会话 ==========
        session = _get_session_value(session_id, None)

        # ========== 2. 内存未命中 → 从数据库重建 ==========
        if not session:
            logger.warning(f"[Planning API] [{session_id}] 审查时内存会话未命中，尝试从数据库重建")
            session = await _rebuild_session_from_db(session_id)
            if not session:
                raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")
            logger.info(f"[Planning API] [{session_id}] 审查时已从数据库重建内存会话")

        # ========== 3. 获取状态并执行审查操作 ==========
        initial_state = session.get("initial_state", {})
        review_id = initial_state.get("review_id", "")
        is_pause_mode = initial_state.get("pause_after_step", False)

        if not review_id and not is_pause_mode and request.action != "rollback":
            raise HTTPException(status_code=400, detail="No pending review or pause")

        from src.tools.web_review_tool import WebReviewTool
        web_review_tool = WebReviewTool()

        # ---------- approve ----------
        if request.action == "approve":
            logger.info(f"[Planning API] [{session_id}] 批准请求 - 状态检查")
            logger.info(f"[Planning API] [{session_id}]   - review_id: {review_id}")
            logger.info(f"[Planning API] [{session_id}]   - pause_after_step: {is_pause_mode}")
            logger.info(f"[Planning API] [{session_id}]   - current_layer: {initial_state.get('current_layer', 1)}")

            # 重置流状态
            _stream_states[session_id] = "active"

            session["status"] = TaskStatus.running

            # ✅ LangGraph 官方推荐模式：
            # 使用 aupdate_state 更新 Checkpoint，而不是操作内存 initial_state
            checkpointer = await get_global_checkpointer()
            graph = create_village_planning_graph(checkpointer=checkpointer)
            config = {"configurable": {"thread_id": session_id}}
            
            # 获取当前 Checkpoint 状态
            checkpoint_state = await graph.aget_state(config)
            if not checkpoint_state or not checkpoint_state.values:
                raise HTTPException(status_code=400, detail="Session not found in checkpoint")
            
            current_layer = checkpoint_state.values.get("current_layer", 1)
            
            # 计算下一层
            next_layer = current_layer
            if current_layer == 1 and checkpoint_state.values.get("layer_1_completed", False):
                next_layer = 2
                logger.info(f"[Planning API] [{session_id}] Layer 1完成，进入Layer 2")
            elif current_layer == 2 and checkpoint_state.values.get("layer_2_completed", False):
                next_layer = 3
                logger.info(f"[Planning API] [{session_id}] Layer 2完成，进入Layer 3")
            elif current_layer == 3 and checkpoint_state.values.get("layer_3_completed", False):
                next_layer = 4
                logger.info(f"[Planning API] [{session_id}] Layer 3完成，进入最终阶段")

            # 更新 Checkpoint
            await graph.aupdate_state(config, {
                "pause_after_step": False,
                "previous_layer": 0,
                "human_feedback": "",
                "current_layer": next_layer,
            })
            logger.info(f"[Planning API] [{session_id}] 已更新 Checkpoint: current_layer={next_layer}")

            # 清除sent_pause_events中之前层的pause事件，确保新层的pause事件能够触发
            sent_pause_events = session.get("sent_pause_events", set())
            if sent_pause_events:
                # 清除所有<=当前层的pause事件
                events_to_clear = [e for e in sent_pause_events if f"pause_layer_{current_layer}" in e]
                if events_to_clear:
                    logger.info(f"[Planning API] [{session_id}] 清除旧的pause事件: {events_to_clear}")
                    for event_key in events_to_clear:
                        sent_pause_events.discard(event_key)
                    session["sent_pause_events"] = sent_pause_events

            # 持久化业务元数据到数据库
            await update_session_async(session_id, {
                "status": TaskStatus.running,
            })

            if review_id:
                web_review_tool.submit_review_decision(review_id=review_id, action="approve")

            logger.info(f"[Planning API] Review approved, resuming session {session_id}")
            # ✅ 不传入 state，让 _resume_graph_execution 从 Checkpoint 加载完整状态
            return await _resume_graph_execution(session_id)

        # ---------- reject ----------
        elif request.action == "reject":
            # ✅ LangGraph 官方推荐模式：
            # 1. Checkpoint 是唯一数据源，不需要操作内存 initial_state
            # 2. 使用 aupdate_state 增量更新 Checkpoint
            # 3. _resume_graph_execution 从 Checkpoint 加载完整状态
            
            session["status"] = TaskStatus.revising

            # 获取 checkpointer 和图实例
            checkpointer = await get_global_checkpointer()
            graph = create_village_planning_graph(checkpointer=checkpointer)
            config = {"configurable": {"thread_id": session_id}}
            
            # ✅ 使用 aupdate_state 增量更新 Checkpoint（不覆盖现有 reports）
            await graph.aupdate_state(config, {
                "need_revision": True,
                "revision_target_dimensions": request.dimensions,
                "human_feedback": request.feedback,
                "pause_after_step": False,
            })
            logger.info(f"[Planning API] [{session_id}] 已更新 Checkpoint:")
            logger.info(f"[Planning API] [{session_id}]   - need_revision: True")
            logger.info(f"[Planning API] [{session_id}]   - revision_target_dimensions: {request.dimensions}")
            logger.info(f"[Planning API] [{session_id}]   - human_feedback: {request.feedback[:50]}...")

            # 持久化业务元数据到数据库
            await update_session_async(session_id, {
                "status": TaskStatus.revising,
                "execution_error": None,
            })

            if review_id:
                web_review_tool.submit_review_decision(
                    review_id=review_id,
                    action="reject",
                    feedback=request.feedback,
                    target_dimensions=request.dimensions
                )

            logger.info(f"[Planning API] Review rejected with feedback, session {session_id}")
            # ✅ 不传入 state，让 _resume_graph_execution 从 Checkpoint 加载完整状态
            return await _resume_graph_execution(session_id)

        # ---------- rollback ----------
        elif request.action == "rollback":
            if not request.checkpoint_id:
                raise HTTPException(status_code=400, detail="Checkpoint ID required for rollback")

            # 使用 LangGraph 统一检查点管理
            try:
                # 1. 获取全局 checkpointer
                checkpointer = await get_global_checkpointer()

                # 2. 创建图实例用于状态操作
                graph = create_village_planning_graph(checkpointer=checkpointer)

                # 3. 构建配置
                config = {"configurable": {"thread_id": session_id}}

                # 4. 从 LangGraph 检查点历史中查找目标检查点
                target_state_snapshot = None
                async for state_snapshot in graph.aget_state_history(config):
                    snapshot_checkpoint_id = state_snapshot.config.get("configurable", {}).get("checkpoint_id", "")
                    if snapshot_checkpoint_id == request.checkpoint_id:
                        target_state_snapshot = state_snapshot
                        break

                if not target_state_snapshot:
                    raise HTTPException(
                        status_code=404,
                        detail=f"Checkpoint not found: {request.checkpoint_id}"
                    )

                # 5. 使用 aupdate_state 恢复状态
                target_values = target_state_snapshot.values
                await graph.aupdate_state(
                    config,
                    target_values,
                    as_node=None  # 不指定节点，直接覆盖状态
                )

                logger.info(f"[Planning API] Successfully rolled back to checkpoint {request.checkpoint_id}")

                # 6. 更新 session 元数据（不更新 initial_state，Checkpoint 是唯一数据源）
                target_layer = target_values.get("current_layer", 1)
                session["current_layer"] = target_layer
                session["status"] = TaskStatus.paused

                # 7. 提交审查决定
                if review_id:
                    web_review_tool.submit_review_decision(
                        review_id=review_id,
                        action="rollback",
                        checkpoint_id=request.checkpoint_id
                    )

                # 8. 持久化业务元数据到数据库
                await update_session_async(session_id, {
                    "status": TaskStatus.paused,
                })

                logger.info(f"[Planning API] Rolling back session {session_id} to layer {target_layer}")

                return {
                    "message": f"Rolled back to checkpoint {request.checkpoint_id}",
                    "current_layer": target_layer,
                    "resumed": False  # 回退后不自动恢复，等待用户确认
                }

            except HTTPException:
                raise
            except Exception as rollback_error:
                logger.error(f"[Planning API] Rollback error: {rollback_error}", exc_info=True)
                raise HTTPException(
                    status_code=500,
                    detail=f"Rollback failed: {str(rollback_error)}"
                )

        else:
            raise HTTPException(status_code=400, detail=f"Invalid action: {request.action}")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[Planning API] Review action error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Review action failed: {str(e)}")

@router.delete("/api/planning/sessions/{session_id}")
async def delete_session(session_id: str):
    """
    Delete a session

    Removes session from memory. Checkpoint data is preserved by default.
    """
    try:
        if session_id not in _sessions:
            raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

        del _sessions[session_id]

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

    Loads checkpoint state from LangGraph and creates new session for continued execution.
    """
    try:
        session_id = _generate_session_id()
        logger.info(f"[Planning API] Resuming from checkpoint {request.checkpoint_id}")

        # 使用 LangGraph API 获取检查点状态
        checkpointer = await get_global_checkpointer()
        graph = create_village_planning_graph(checkpointer=checkpointer)

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

        with _sessions_lock:
            _sessions[session_id] = {
                "session_id": session_id,
                "project_name": request.project_name,
                "status": TaskStatus.running,
                "created_at": datetime.now().isoformat(),
                "resumed_from": request.checkpoint_id,
                "current_layer": target_layer,
                "initial_state": state,
                "events": deque(maxlen=MAX_SESSION_EVENTS),
                "execution_complete": False,
                "execution_error": None,
            }

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
        session_id: 可选的会话 ID，用于精确获取检查点
    """
    try:
        checkpointer = await get_global_checkpointer()
        graph = create_village_planning_graph(checkpointer=checkpointer)

        # 使用 session_id 作为 thread_id
        thread_id = session_id or project_name
        config = {"configurable": {"thread_id": thread_id}}

        checkpoints = []
        async for state_snapshot in graph.aget_state_history(config):
            checkpoint_id = state_snapshot.config.get("configurable", {}).get("checkpoint_id", "")
            values = state_snapshot.values or {}

            # 构建检查点信息
            checkpoint_info = {
                "checkpoint_id": checkpoint_id,
                "timestamp": state_snapshot.metadata.get("write_ts", "") if state_snapshot.metadata else "",
                "layer": values.get("current_layer", 1),
                "description": f"Layer {values.get('current_layer', 1)} checkpoint",
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
    """从数据库重建内存会话（字典版本）"""
    db_session = await get_session_async(session_id)
    if not db_session:
        return None

    # ✅ 新增：从 checkpointer 恢复 state
    saver = await get_global_checkpointer()
    graph = create_village_planning_graph(checkpointer=saver)
    config = {"configurable": {"thread_id": session_id}}

    try:
        state_snapshot = await graph.aget_state(config)
        initial_state = state_snapshot.values if state_snapshot else {}
        logger.info(f"[Planning API] [{session_id}] 已从 LangGraph checkpoint 恢复 state: pause_after_step={initial_state.get('pause_after_step', False)}, current_layer={initial_state.get('current_layer', 1)}")
    except Exception as e:
        logger.warning(f"[Planning API] [{session_id}] 无法从 checkpoint 恢复 state: {e}")
        initial_state = {}

    with _sessions_lock:
        # 根据层级完成状态恢复 sent_layer_events，防止重复发送已完成的事件
        sent_layer_events = set()
        if initial_state.get("layer_1_completed"):
            sent_layer_events.add("layer_1_completed")
        if initial_state.get("layer_2_completed"):
            sent_layer_events.add("layer_2_completed")
        if initial_state.get("layer_3_completed"):
            sent_layer_events.add("layer_3_completed")
        
        logger.info(f"[Planning API] [{session_id}] 恢复 sent_layer_events: {sent_layer_events}")
        
        _sessions[session_id] = {
            # ✅ 只从数据库读取业务元数据
            "session_id": db_session["session_id"],
            "project_name": db_session["project_name"],
            "status": db_session["status"],
            "execution_error": db_session.get("execution_error"),
            "created_at": db_session["created_at"].isoformat() if isinstance(db_session["created_at"], datetime) else db_session["created_at"],
            # ✅ 内存中的状态管理
            "events": deque(maxlen=MAX_SESSION_EVENTS),
            "execution_complete": False,
            "sent_layer_events": sent_layer_events,  # ✅ 恢复而非重置
            "sent_revised_events": set(),  # 修订事件不持久化，恢复时重置
            "sent_pause_events": set(),
            # ✅ 从 AsyncSqliteSaver 恢复 state
            "initial_state": initial_state,
            "current_layer": initial_state.get("current_layer", 1),
        }
    logger.info(f"[Planning API] [{session_id}] 已从数据库重建内存会话")
    return _sessions[session_id]
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
