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
import copy
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

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
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
    delete_planning_session_async as delete_session_async,
    # UI 消息存储操作
    create_ui_message_async,
    get_ui_messages_async,
    upsert_ui_message_async,  # ✅ 新增：upsert 消息
    delete_ui_messages_async,
)
# ✅ 从 engine 导入数据库路径函数
from backend.database.engine import get_db_path

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
    logger.info("[SSE] 主事件循环已保存，跨线程事件发布已启用")


# ============================================
# Global Checkpointer Management
# ============================================

_checkpointer: Optional[Any] = None
_checkpointer_lock = asyncio.Lock()
_checkpointer_initialized = False

# ============================================
# 🔧 跨线程安全事件发布 - 主事件循环引用
# ============================================
# 用于在 LLM 回调的同步线程中安全地发布 SSE 事件
_main_event_loop: Optional[asyncio.AbstractEventLoop] = None


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
MAX_SESSION_EVENTS = 5000  # Maximum events to keep per session (增加容量以支持更长的规划会话)
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

# ✅ 全局事件计数器：用于为每个事件分配唯一 ID，解决 deque rotation 问题
_event_counter = 0
_event_counter_lock = Lock()

# Thread safety locks
_sessions_lock = Lock()
_active_executions_lock = Lock()
_stream_states_lock = Lock()

# 🔧 新增：asyncio.Queue 订阅管理系统（每个 SSE 连接独立队列）
_session_subscribers: Dict[str, set] = {}  # session_id -> set of asyncio.Queue


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
    会话清理循环
    
    每隔 EVENT_CLEANUP_INTERVAL_SECONDS 秒执行一次清理，
    移除超过 SESSION_TTL_HOURS 小时的过期会话状态。
    """
    from datetime import timedelta
    
    logger.info("[Session Cleanup] 清理循环开始运行")
    
    while _cleanup_running:
        try:
            await asyncio.sleep(EVENT_CLEANUP_INTERVAL_SECONDS)
            
            if not _cleanup_running:
                break
            
            now = datetime.now()
            cutoff_time = now - timedelta(hours=SESSION_TTL_HOURS)
            
            # 统计清理数量
            cleaned_sessions = 0
            cleaned_executions = 0
            cleaned_streams = 0
            cleaned_log_trackers = 0
            
            # 清理过期的 _sessions
            with _sessions_lock:
                expired_session_ids = [
                    sid for sid, sdata in _sessions.items()
                    if sdata.get("updated_at") and sdata["updated_at"] < cutoff_time
                ]
                for sid in expired_session_ids:
                    del _sessions[sid]
                    cleaned_sessions += 1
            
            # 清理孤儿状态的 _active_executions（对应 session 不存在）
            with _sessions_lock, _active_executions_lock:
                orphan_executions = [
                    sid for sid in _active_executions
                    if sid not in _sessions
                ]
                for sid in orphan_executions:
                    del _active_executions[sid]
                    cleaned_executions += 1
            
            # 清理孤儿状态的 _stream_states
            with _sessions_lock, _stream_states_lock:
                orphan_streams = [
                    sid for sid in _stream_states
                    if sid not in _sessions
                ]
                for sid in orphan_streams:
                    del _stream_states[sid]
                    cleaned_streams += 1
            
            # 清理孤儿状态的 _status_log_tracker
            with _sessions_lock, _status_log_lock:
                orphan_trackers = [
                    sid for sid in _status_log_tracker
                    if sid not in _sessions
                ]
                for sid in orphan_trackers:
                    del _status_log_tracker[sid]
                    cleaned_log_trackers += 1
            
            total_cleaned = cleaned_sessions + cleaned_executions + cleaned_streams + cleaned_log_trackers
            
            if total_cleaned > 0:
                logger.info(
                    f"[Session Cleanup] 🧹 清理完成: "
                    f"sessions={cleaned_sessions}, executions={cleaned_executions}, "
                    f"streams={cleaned_streams}, trackers={cleaned_log_trackers}"
                )
            else:
                logger.debug(f"[Session Cleanup] 本次清理无需处理（当前活跃会话: {len(_sessions)}）")
                
        except asyncio.CancelledError:
            logger.info("[Session Cleanup] 清理循环被取消")
            break
        except Exception as e:
            logger.error(f"[Session Cleanup] 清理循环出错: {e}", exc_info=True)
            await asyncio.sleep(60)  # 出错后等待 1 分钟再重试


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


def _append_session_event(session_id: str, event: Dict) -> int:
    """
    Thread-safe append event to session events list
    
    注意：events 使用 deque(maxlen=MAX_SESSION_EVENTS)，会自动丢弃最旧的事件，
    无需手动裁剪。

    Args:
        session_id: Session identifier
        event: Event dictionary to append

    Returns:
        The event_id assigned to this event, or -1 if failed
    """
    global _event_counter
    with _sessions_lock:
        if session_id in _sessions:
            events = _sessions[session_id].setdefault("events", [])
            
            # ✅ 为事件分配唯一 ID
            with _event_counter_lock:
                _event_counter += 1
                event_id = _event_counter
            event["_event_id"] = event_id
            events.append(event)  # deque 会自动限制大小（maxlen）
            
            # 🔧 发布事件到 asyncio.Queue 订阅者
            _publish_event_sync(session_id, event)
            
            return event_id
    return -1


# ============================================
# ✅ 新增：异步版本的事件追加函数
# ============================================

async def _append_session_event_async(session_id: str, event: Dict) -> bool:
    """
    异步版本的会话事件追加（高性能）

    使用异步数据库操作替代内存操作，
    显著提升高并发场景下的性能。
    
    注意：events 使用 deque(maxlen=MAX_SESSION_EVENTS)，会自动丢弃最旧的事件。

    Args:
        session_id: Session identifier
        event: Event dictionary to append

    Returns:
        True: 成功, False: 失败
    """
    global _event_counter
    # ✅ 先分配唯一 ID（在任何存储之前）
    with _event_counter_lock:
        _event_counter += 1
        event["_event_id"] = _event_counter

    try:
        # 使用异步数据库包装器
        success = await add_event_async(session_id, event)
        if success:
            logger.debug(f"[Async DB] Event appended to session {session_id}")
            # 同时更新内存缓存（不再调用 _append_session_event 避免重复分配 ID）
            with _sessions_lock:
                if session_id in _sessions:
                    events = _sessions[session_id].setdefault("events", [])
                    events.append(event)  # deque 会自动限制大小（maxlen）
            # ✅ 发布事件到 SSE 订阅者（修复连续模式 layer_completed 事件丢失问题）
            _publish_event_sync(session_id, event)
        return success
    except Exception as e:
        logger.error(f"[Async DB] Failed to append event: {e}", exc_info=True)
        # 失败时回退到内存版本（event_id 已经分配）
        with _sessions_lock:
            if session_id in _sessions:
                events = _sessions[session_id].setdefault("events", [])
                events.append(event)  # deque 会自动限制大小（maxlen）
        # ✅ 发布事件到 SSE 订阅者（修复连续模式 layer_completed 事件丢失问题）
        _publish_event_sync(session_id, event)
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

# ✅ SSOT 优化：频率控制参数（大幅减少事件数量，避免队列阻塞）
DELTA_MIN_INTERVAL_MS = 500  # 最小发送间隔（毫秒）- 从 200ms 增加到 500ms
DELTA_MIN_TOKENS = 50        # 最小 token 数量 - 从 20 增加到 50 tokens

# 事件队列大小限制（防止内存爆炸）
MAX_EVENTS_PER_SESSION = 500   # 每个会话最大事件数


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
        
        # 调试：每10次打印一次状态
        if token_count % 10 == 0:
            logger.debug(f"[dimension_delta] {dimension_key}: token_count={token_count}, time_elapsed={time_elapsed:.0f}ms, should_send={should_send}")
        
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
        
        # 精简日志：只在里程碑时打印
        milestones = {500, 1000, 2000, 5000, 10000}
        hit_milestone = any(abs(len(accumulated) - m) < 50 for m in milestones)
        if token_count == 1 or hit_milestone:
            logger.debug(f"[dimension_delta] {dimension_key}: {len(accumulated)} chars")
        
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


def flush_dimension_delta(
    session_id: str,
    layer: int,
    dimension_key: str,
    dimension_name: str,
    final_accumulated: str
) -> None:
    """
    在维度生成结束时，强制将缓冲池中剩余的 token 发送出去
    
    由于频率控制（200ms/20 tokens），最后不满条件的 token 会被缓存，
    调用此函数可确保所有内容都被发送，避免"内容不完整"问题。
    
    Args:
        session_id: 会话ID
        layer: 层级编号 (1/2/3)
        dimension_key: 维度键名
        dimension_name: 维度显示名称
        final_accumulated: 最终完整的累积文本
    """
    cache_key = f"{session_id}:{layer}:{dimension_key}"
    with _dimension_delta_lock:
        token_count = _dimension_delta_token_count.get(cache_key, 0)
        
        # 只要有未发送的增量，就发送一次完整状态
        if token_count > 0:
            event_data = {
                "type": "dimension_delta",
                "layer": layer,
                "dimension_key": dimension_key,
                "dimension_name": dimension_name,
                "accumulated": final_accumulated,  # 发送完整文本
                "delta": "",  # 增量为空
                "timestamp": datetime.now().isoformat()
            }
            _append_session_event(session_id, event_data)
            
            # 清零计数器
            _dimension_delta_token_count[cache_key] = 0
            logger.debug(f"[flush_dimension_delta] {dimension_key}: flushed {token_count} remaining tokens, total={len(final_accumulated)} chars")


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
        
        graph = create_village_planning_graph(checkpointer=checkpointer)
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
        
        layer_names = {1: "现状分析", 2: "规划思路", 3: "详细规划"}
        
        # 重建 layer_completed 事件
        for layer_num in [1, 2, 3]:
            if state.get(f"layer_{layer_num}_completed", False):
                # 获取维度报告
                if layer_num == 1:
                    dimension_reports = state.get("analysis_reports", {})
                elif layer_num == 2:
                    dimension_reports = state.get("concept_reports", {})
                else:
                    dimension_reports = state.get("detail_reports", {})
                
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
                    "previous_layer": state.get("previous_layer", 0),
                    "timestamp": metadata.get("last_signal_timestamp", datetime.now().isoformat()),
                    # 标记：此事件来自 Checkpoint 重建
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
    
    每个 SSE 连接获得独立的队列，实现：
    - 事件驱动模式（无需轮询）
    - 多客户端支持
    - 无竞态条件
    - 🔧 历史事件同步（确保 SSE 连接前的事件不丢失）
    - 🔧 Checkpoint 重建（服务重启后恢复状态）
    
    Args:
        session_id: 会话 ID
        
    Returns:
        asyncio.Queue: 专用于该连接的事件队列
    """
    queue = asyncio.Queue(maxsize=200)  # 每个客户端最多缓存 200 个事件
    
    if session_id not in _session_subscribers:
        _session_subscribers[session_id] = set()
    _session_subscribers[session_id].add(queue)
    
    # 🔧 关键修复：同步历史事件到新订阅者
    # 解决 SSE 连接建立前事件丢失的问题
    historical_count = 0
    event_type_counts: Dict[str, int] = {}  # 🔧 新增：按类型统计事件数量
    layer_completed_found = False
    
    with _sessions_lock:
        if session_id in _sessions:
            # events 是 deque，直接遍历
            events = _sessions[session_id].get("events", [])
            for event in events:
                try:
                    queue.put_nowait(event)
                    historical_count += 1
                    # 🔧 新增：按类型统计
                    event_type = event.get("type", "unknown")
                    event_type_counts[event_type] = event_type_counts.get(event_type, 0) + 1
                    # 🔧 新增：检测 layer_completed 事件
                    if event_type == "layer_completed":
                        layer_completed_found = True
                except asyncio.QueueFull:
                    logger.warning(f"[SSE Subscribe] Session {session_id}: 队列已满，丢弃历史事件")
                    break
    
    # 🔧 新增：如果内存中没有历史事件或缺少关键事件，从 Checkpoint 重建
    if historical_count == 0 or not layer_completed_found:
        logger.info(f"[SSE Subscribe] Session {session_id}: 尝试从 Checkpoint 重建事件 (内存事件={historical_count}, layer_completed={layer_completed_found})")
        rebuilt_events = await _rebuild_events_from_checkpoint(session_id)
        
        if rebuilt_events:
            for event in rebuilt_events:
                try:
                    queue.put_nowait(event)
                    event_type = event.get("type", "unknown")
                    event_type_counts[event_type] = event_type_counts.get(event_type, 0) + 1
                    historical_count += 1
                    if event_type == "layer_completed":
                        layer_completed_found = True
                except asyncio.QueueFull:
                    logger.warning(f"[SSE Subscribe] Session {session_id}: 队列已满，丢弃重建事件")
                    break
    
    # 🔧 新增：详细日志，包括事件类型分布
    logger.info(f"[SSE Subscribe] Session {session_id}: 订阅者数量 = {len(_session_subscribers[session_id])}, 同步历史事件 = {historical_count}")
    if historical_count > 0:
        logger.info(f"[SSE Subscribe] Session {session_id}: 历史事件类型分布 = {event_type_counts}")
        if layer_completed_found:
            logger.info(f"[SSE Subscribe] Session {session_id}: ✅ 历史事件中包含 layer_completed")
        else:
            logger.info(f"[SSE Subscribe] Session {session_id}: ⚠️ 历史事件中没有 layer_completed")
    
    return queue


async def unsubscribe_session(session_id: str, queue: asyncio.Queue) -> None:
    """
    取消订阅 session 的事件流
    
    Args:
        session_id: 会话 ID
        queue: 要移除的队列
    """
    if session_id in _session_subscribers:
        _session_subscribers[session_id].discard(queue)
        if not _session_subscribers[session_id]:
            del _session_subscribers[session_id]
            logger.debug(f"[SSE Unsubscribe] Session {session_id}: 无订阅者，清理订阅表")
        else:
            logger.debug(f"[SSE Unsubscribe] Session {session_id}: 剩余订阅者数量 = {len(_session_subscribers[session_id])}")


async def publish_event_to_subscribers(session_id: str, event: Dict) -> None:
    """
    发布事件到所有订阅者
    
    Args:
        session_id: 会话 ID
        event: 事件字典
    """
    subscribers = _session_subscribers.get(session_id, set())
    event_type = event.get("type", "unknown")
    
    # 🔧 新增：对于重要事件类型，打印订阅者数量
    if event_type in ["layer_completed", "layer_started", "pause", "stream_paused", "dimension_complete"]:
        logger.info(f"[SSE Publish] Session {session_id}: 事件类型={event_type}, 订阅者数量={len(subscribers)}")
    
    if not subscribers:
        # 🔧 新增：对于重要事件，记录无订阅者的警告
        if event_type in ["layer_completed", "dimension_complete"]:
            logger.warning(f"[SSE Publish] Session {session_id}: ⚠️ 事件 {event_type} 无订阅者！事件将丢失！")
        return
    
    # 统计成功/失败数量
    success_count = 0
    dropped_count = 0
    
    for queue in list(subscribers):  # 使用 list() 避免迭代时修改
        try:
            queue.put_nowait(event)
            success_count += 1
        except asyncio.QueueFull:
            # 队列满：客户端处理太慢，丢弃该事件
            dropped_count += 1
    
    # 🔧 新增：对于重要事件，记录发送结果
    if event_type in ["layer_completed", "layer_started", "pause", "dimension_complete"]:
        if dropped_count > 0:
            logger.warning(f"[SSE Publish] Session {session_id}: {event_type} 发送结果: {success_count} 成功, {dropped_count} 因队列满丢弃")
        else:
            logger.info(f"[SSE Publish] Session {session_id}: ✅ {event_type} 已发送到 {success_count} 个订阅者")


def _publish_event_sync(session_id: str, event: Dict) -> None:
    """
    同步版本的发布函数 - 供 LLM 回调调用
    
    🔧 跨线程安全：优先使用保存的主事件循环 _main_event_loop
    使用 asyncio.run_coroutine_threadsafe 从同步代码调用异步发布
    
    Args:
        session_id: 会话 ID
        event: 事件字典
    """
    event_type = event.get("type", "unknown")
    
    # 🔧 检查订阅者数量
    subscribers = _session_subscribers.get(session_id, set())
    subscriber_count = len(subscribers)
    
    # 🔧 对于重要事件，记录调用详情
    if event_type in ["dimension_delta", "dimension_complete"]:
        if subscriber_count > 0:
            logger.debug(f"[SSE Publish Sync] Session {session_id}: {event_type}, 订阅者={subscriber_count}")
    elif event_type in ["layer_completed", "layer_started"]:
        logger.info(f"[SSE Publish Sync] Session {session_id}: {event_type}, 订阅者={subscriber_count}")
    
    # 🔧 跨线程安全：优先使用保存的主事件循环
    loop = None
    loop_source = None
    
    if _main_event_loop is not None:
        loop = _main_event_loop
        loop_source = "saved_main_loop"
    else:
        # 回退：尝试获取当前运行的事件循环
        try:
            loop = asyncio.get_running_loop()
            loop_source = "current_loop"
        except RuntimeError:
            pass
    
    if loop is None:
        # 没有可用的事件循环
        if event_type in ["layer_completed", "dimension_complete"]:
            logger.warning(f"[SSE Publish Sync] Session {session_id}: ⚠️ 无可用事件循环，事件 {event_type} 无法发送！")
        else:
            logger.debug(f"[SSE Publish Sync] No event loop available, skipping {event_type}")
        return
    
    try:
        # 从同步代码安全地调用异步函数
        future = asyncio.run_coroutine_threadsafe(
            publish_event_to_subscribers(session_id, event),
            loop
        )
        # 🔧 非阻塞模式：不等待结果，事件在后台发送
        # 原来的 future.result(timeout=5.0) 会导致每次事件发送阻塞最多 5 秒
        # 改为 fire-and-forget 模式，提高响应速度
        # future.result(timeout=5.0)  # 已移除阻塞等待
        
        if event_type in ["layer_completed", "layer_started", "dimension_complete"]:
            logger.info(f"[SSE Publish Sync] Session {session_id}: ✅ {event_type} 已通过 {loop_source} 发送（非阻塞）")
    except Exception as e:
        if event_type in ["layer_completed", "dimension_complete"]:
            logger.error(f"[SSE Publish Sync] Session {session_id}: ⚠️ 发送 {event_type} 失败: {e}")
        else:
            logger.debug(f"[SSE Publish Sync] Failed to send {event_type}: {e}")


def _get_session_events_copy(session_id: str) -> list:
    """
    Thread-safe get deep copy of session events list
    
    使用深拷贝防止 "deque mutated during iteration" 错误：
    当写入线程正在追加事件时，如果读取协程正好在遍历队列，
    浅拷贝会导致 RuntimeError: deque mutated during iteration。
    
    Args:
        session_id: Session identifier

    Returns:
        Deep copy of events list or empty list if session not found
    """
    with _sessions_lock:
        if session_id not in _sessions:
            return []
        # 🔧 使用深拷贝，确保事件对象不会被其他线程修改
        return copy.deepcopy(_sessions[session_id].get("events", []))


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

        # 【新增】元数据 - 持久化到 Checkpoint，用于去重和版本化同步
        "metadata": {
            "published_layers": [],      # 已发送 layer_completed 信号的层级
            "version": 0,                # 状态版本号
            "last_signal_timestamp": None,
        },

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
    事件直接写入 _sessions[session_id]["events"] 列表。
    
    ✅ SSOT 简化：不再使用 sent_*_events 集合进行内存去重
    - LangGraph 的状态变化是原子的，每次 astream 返回的事件都是唯一的状态变化
    - SSE 事件是"阅后即焚"的，不需要持久化去重状态
    """
    logger.info(f"[Planning] [{session_id}] ===== 后台执行开始 =====")
    logger.info(f"[Planning] [{session_id}] Graph 类型: {type(graph).__name__}")
    logger.info(f"[Planning] [{session_id}] Checkpointer: {checkpointer}")

    try:
        config = {"configurable": {"thread_id": session_id}}

        # ✅ 移除：不再需要获取 sent_*_events 集合
        # 跟踪已发送的 layer_started 事件（用于本执行周期内的去重，不持久化）
        sent_layer_started_this_run = set()
        
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
        # 修复: 从 checkpoint 恢复时 initial_state 为 None，默认启用流式输出
        streaming_enabled = (initial_state.get("_streaming_enabled", True) if initial_state else True)
        if streaming_enabled:
            config["configurable"]["_token_callback_factory"] = token_callback_factory
            logger.info(f"[Planning] [{session_id}] Token 回调工厂已放入 config (streaming_enabled={streaming_enabled})")

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

        # ✅ 持久化去重：从 Checkpoint metadata 读取已发送的层级信号
        # 不再使用内存 set，避免服务重启后状态丢失
        checkpoint_state = await graph.aget_state(config)
        metadata = checkpoint_state.values.get("metadata", {})
        published_layers = set(metadata.get("published_layers", []))
        logger.info(f"[Planning] [{session_id}] 从 Checkpoint 读取 published_layers: {published_layers}")
        
        # ✅ 持久化去重：读取已发送的修订维度信号
        published_revisions = set(metadata.get("published_revisions", []))
        logger.info(f"[Planning] [{session_id}] 从 Checkpoint 读取 published_revisions: {published_revisions}")

        # 执行周期内的临时去重（用于 layer_started 和 pause，这些不需要持久化）
        sent_layer_started_this_run = set()
        sent_pause_this_run = set()

        async for event in stream_iterator:
            # ✅ 检测层级开始（layer_started 事件）
            # 关键修复：检查是否是真正的层级开始执行，而不是层级完成后的状态更新
            current_layer = event.get("current_layer")
            pause_after_step = event.get("pause_after_step", False)
            previous_layer = event.get("previous_layer", 0)
            step_mode = event.get("step_mode", False)
            
            # 判断是否应该发送 layer_started：
            # 1. current_layer 有效 (1/2/3)
            # 2. 没有暂停
            # 3. 该层级尚未发布过（使用 published_layers 判断，避免重复发送）
            # 4. 🔧 关键修复：step_mode 下，如果 previous_layer > 0，说明刚完成一个层级，应该等待用户批准
            #    而不是立即发送新层级的 layer_started 事件
            should_send_started = (
                current_layer and 
                current_layer in [1, 2, 3] and 
                not pause_after_step and
                not (step_mode and previous_layer > 0) and  # 🔧 新增：step_mode 下层级切换时不发送
                current_layer not in published_layers  # 使用持久化的已发布层级来判断
            )
            
            if should_send_started:
                layer_started_key = f"layer_{current_layer}_started"
                # ✅ 只在本执行周期内去重，不持久化
                if layer_started_key not in sent_layer_started_this_run:
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
                    sent_layer_started_this_run.add(layer_started_key)
                    logger.info(f"[Planning] [{session_id}] ✓ layer_started 事件已发送: Layer {current_layer}")

            # 检测层级完成
            for layer_num in [1, 2, 3]:
                now_completed = event.get(f"layer_{layer_num}_completed", False)

                # ✅ 持久化去重：检查 metadata.published_layers 而不是内存 set
                if now_completed and layer_num not in published_layers:
                    # 获取维度报告内容
                    from src.utils.report_utils import (
                        generate_analysis_report,
                        generate_concept_report,
                        generate_detail_report
                    )
                    
                    project_name = event.get("project_name", "村庄")
                    
                    if layer_num == 1:
                        dimension_reports = event.get("analysis_reports", {})
                    elif layer_num == 2:
                        dimension_reports = event.get("concept_reports", {})
                        logger.info(f"[Planning] [{session_id}] === Layer 2 完成 ===")
                        logger.info(f"[Planning] [{session_id}] concept_reports: {list(dimension_reports.keys()) if dimension_reports else 'empty'}")
                    else:  # layer_num == 3
                        dimension_reports = event.get("detail_reports", {})
                        logger.info(f"[Planning] [{session_id}] === Layer 3 完成 ===")
                        logger.info(f"[Planning] [{session_id}] detail_reports: {list(dimension_reports.keys()) if dimension_reports else 'empty'}")

                    # 数据完整性验证
                    total_dimension_content = sum(len(v) for v in dimension_reports.values()) if dimension_reports else 0
                    
                    if not dimension_reports:
                        logger.warning(f"[Planning] [{session_id}] ⚠️ Layer {layer_num} dimension_reports 为空！")
                    else:
                        logger.info(f"[Planning] [{session_id}] ✓ Layer {layer_num} 数据完整: {len(dimension_reports)} 个维度, {total_dimension_content} 字符")

                    # ✅ Signal-Fetch Pattern: SSE 只发送轻量信号
                    event_data = {
                        "type": "layer_completed",
                        "layer": layer_num,
                        "layer_number": layer_num,
                        "session_id": session_id,
                        "message": f"Layer {layer_num} completed",
                        "has_data": len(dimension_reports) > 0 and total_dimension_content > 0,
                        "dimension_count": len(dimension_reports) if dimension_reports else 0,
                        "total_chars": total_dimension_content,
                        "pause_after_step": event.get("pause_after_step", False),
                        "previous_layer": event.get("previous_layer", 0),
                        "timestamp": datetime.now().isoformat()
                    }
                    
                    logger.info(f"[Planning] [{session_id}] ✓ layer_completed 信号: Layer {layer_num}, dims={event_data['dimension_count']}")
                    
                    # 发送事件
                    await _append_session_event_async(session_id, event_data)
                    
                    # ✅ 持久化更新：将层级添加到 published_layers，并递增版本号
                    published_layers.add(layer_num)
                    current_metadata = event.get("metadata", {})
                    current_version = current_metadata.get("version", 0)
                    updated_metadata = {
                        **current_metadata,
                        "published_layers": list(published_layers),
                        "version": current_version + 1,  # 【新增】递增版本号
                        "last_signal_timestamp": datetime.now().isoformat(),
                    }
                    await graph.aupdate_state(config, {"metadata": updated_metadata})
                    logger.info(f"[Planning] [{session_id}] ✅ 已更新 metadata: published_layers={list(published_layers)}, version={current_version + 1}")
                    
                    # 检查 SSE 订阅者状态
                    subscribers = _session_subscribers.get(session_id, set())
                    subscriber_count = len(subscribers)
                    if subscriber_count == 0:
                        logger.warning(f"[Planning] [{session_id}] ⚠️ layer_completed 发送时无 SSE 订阅者！")

            # 【简化】检测修复完成事件
            last_revised_dimensions = event.get("last_revised_dimensions", [])
            if last_revised_dimensions and not event.get("need_revision", False):
                logger.info(f"[Planning] [{session_id}] === 检测到修复完成: {last_revised_dimensions} ===")
                
                revision_history = event.get("revision_history", [])
                new_published_revisions = set()  # 本次需要添加的修订
                
                for dim in last_revised_dimensions:
                    latest_revision = next(
                        (r for r in reversed(revision_history) if r.get("dimension") == dim),
                        None
                    )
                    
                    if latest_revision:
                        layer = latest_revision.get("layer", 1)
                        new_content = latest_revision.get("new_content", "")
                        revision_timestamp = latest_revision.get("timestamp", datetime.now().isoformat())
                        old_content = latest_revision.get("old_content", "")  # 获取修复前的内容
                        
                        # ✅ 去重：使用 dimension + timestamp 作为唯一标识
                        revision_key = f"{dim}_{revision_timestamp}"
                        if revision_key in published_revisions:
                            logger.info(f"[Planning] [{session_id}] 跳过已发送的修订: {revision_key}")
                            continue
                        
                        # ✅ 记录维度修订历史到数据库（包含 previous_content 用于前端显示修复前后对比）
                        try:
                            from backend.database.operations_async import create_dimension_revision_async
                            await create_dimension_revision_async(
                                session_id=session_id,
                                layer=layer,
                                dimension_key=dim,
                                content=new_content,
                                previous_content=old_content,  # 新增：传入旧内容
                                reason=latest_revision.get("revision_type", "用户修正"),
                                created_by="revision_flow",
                            )
                            logger.info(f"[Planning] [{session_id}] ✓ 维度修订历史已记录: {dim}")
                        except Exception as e:
                            logger.warning(f"[Planning] [{session_id}] 记录维度修订历史失败: {e}")
                        
                        # ✅ Signal-Fetch 模式：SSE 事件不携带报告内容，只发送信号
                        # 前端收到信号后应调用 REST API 获取完整内容
                        event_data = {
                            "type": "dimension_revised",
                            "dimension": dim,
                            "layer": layer,
                            # 不携带 new_content，前端应调用 REST API 获取
                            "timestamp": revision_timestamp
                        }
                        await _append_session_event_async(session_id, event_data)
                        logger.info(f"[Planning] [{session_id}] ✓ dimension_revised 信号已发送: {dim}")
                        
                        # 标记为已发送
                        new_published_revisions.add(revision_key)
                
                # ✅ 更新 metadata：将新发送的修订添加到 published_revisions
                if new_published_revisions:
                    published_revisions.update(new_published_revisions)
                    # 获取当前 metadata 和版本
                    current_state = await graph.aget_state(config)
                    current_metadata = current_state.values.get("metadata", {})
                    current_version = current_state.values.get("version", 0)
                    
                    # 更新 metadata
                    updated_metadata = dict(current_metadata)
                    updated_metadata["published_revisions"] = list(published_revisions)
                    
                    await graph.aupdate_state(
                        config,
                        {"metadata": updated_metadata},
                        as_node=None  # 不指定节点，直接更新状态
                    )
                    logger.info(f"[Planning] [{session_id}] ✅ 已更新 metadata: published_revisions 新增 {new_published_revisions}")

            # ✅ SSOT 简化：不再手动同步内存状态到 _sessions
            # LangGraph Checkpoint 是唯一真实源

            # 检查暂停状态（步进模式）
            if event.get("pause_after_step"):
                logger.info(f"[Planning] [{session_id}] 检测到暂停状态")
                
                previous_layer = event.get("previous_layer", 1)
                pause_event_key = f"pause_layer_{previous_layer}"

                # ✅ 简化：只在本执行周期内去重
                if pause_event_key not in sent_pause_this_run:
                    # ✅ 从 LangGraph checkpoint 获取真实的 checkpoint_id
                    current_state = await graph.aget_state(config)
                    checkpoint_id = current_state.config.get("configurable", {}).get("checkpoint_id", "")
                    logger.info(f"[Planning] [{session_id}] 获取到 checkpoint_id: {checkpoint_id}")
                    
                    pause_event = {
                        "type": "pause",
                        "session_id": session_id,
                        "current_layer": previous_layer,
                        "checkpoint_id": checkpoint_id,
                        "reason": "step_mode",
                        "timestamp": datetime.now().isoformat()
                    }
                    _append_session_event(session_id, pause_event)
                    sent_pause_this_run.add(pause_event_key)
                    
                    # 持久化状态到数据库
                    try:
                        await update_session_async(session_id, {"status": TaskStatus.paused})
                        logger.info(f"[Planning] [{session_id}] 状态已持久化到数据库: paused")
                    except Exception as e:
                        logger.error(f"[Planning] [{session_id}] 持久化状态失败: {e}")

                    stream_paused_event = {
                        "type": "stream_paused",
                        "session_id": session_id,
                        "current_layer": previous_layer,
                        "reason": "waiting_for_resume",
                        "timestamp": datetime.now().isoformat()
                    }
                    await _append_session_event_async(session_id, stream_paused_event)
                    _stream_states[session_id] = "paused"

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
        await _append_session_event_async(session_id, completion_event)
        
        # 更新数据库状态
        try:
            await update_session_async(session_id, {"status": TaskStatus.completed})
        except Exception as e:
            logger.error(f"[Planning] [{session_id}] 持久化状态失败: {e}")
        
        await _set_stream_state(session_id, "completed")
        logger.info(f"[Planning] [{session_id}] 执行完成")

    except Exception as e:
        logger.error(f"[Planning] Execution error for {session_id}: {e}", exc_info=True)

        # 添加错误事件
        error_event = {
            "type": "error",
            "session_id": session_id,
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }
        await _append_session_event_async(session_id, error_event)

        # 更新数据库状态
        try:
            await update_session_async(session_id, {
                "status": TaskStatus.failed,
                "execution_error": str(e)
            })
        except Exception as db_error:
            logger.error(f"[Planning] [{session_id}] 持久化错误状态失败: {db_error}")
        
        await _set_stream_state(session_id, "completed")


async def _resume_graph_execution(session_id: str, state: Dict[str, Any] = None) -> Dict[str, Any]:
    """
    Resume graph execution from checkpoint
    
    ✅ SSOT 简化：
    - Checkpoint 是唯一的数据源（Single Source of Truth）
    - 使用 graph.astream(None, config) 恢复执行
    - 不再维护内存中的 sent_*_events 集合

    Args:
        session_id: Session identifier
        state: (已废弃) 保留参数用于兼容旧调用

    Returns:
        Response with stream URL for resuming execution
    """
    # 使用统一的单例获取方式
    saver = await get_global_checkpointer()
    graph = create_village_planning_graph(checkpointer=saver)
    config = {"configurable": {"thread_id": session_id}}
    
    # 从 Checkpoint 获取完整状态
    checkpoint_state = await graph.aget_state(config)
    if not checkpoint_state or not checkpoint_state.values:
        logger.error(f"[Planning API] [{session_id}] Checkpoint 中未找到会话状态")
        raise HTTPException(
            status_code=400,
            detail=f"Session {session_id} not found in checkpoint"
        )
    
    full_state = checkpoint_state.values
    current_layer = full_state.get("current_layer", 1)
    
    logger.info(f"[Planning API] [{session_id}] 从 Checkpoint 恢复:")
    logger.info(f"[Planning API] [{session_id}]   - current_layer: {current_layer}")
    logger.info(f"[Planning API] [{session_id}]   - layer_1_completed: {full_state.get('layer_1_completed', False)}")
    logger.info(f"[Planning API] [{session_id}]   - layer_2_completed: {full_state.get('layer_2_completed', False)}")
    logger.info(f"[Planning API] [{session_id}]   - layer_3_completed: {full_state.get('layer_3_completed', False)}")

    # 添加 resumed 事件
    _append_session_event(session_id, {
        "type": "resumed",
        "session_id": session_id,
        "current_layer": current_layer,
        "message": "Execution resumed after review approval",
        "timestamp": datetime.now().isoformat()
    })

    # 持久化状态到数据库
    try:
        await update_session_async(session_id, {
            "status": TaskStatus.running,
            "execution_error": None,
        })
        logger.info(f"[Planning API] [{session_id}] 状态已持久化到数据库: status=running")
    except Exception as db_error:
        logger.error(f"[Planning API] [{session_id}] 持久化状态失败: {db_error}")

    # 清除 Checkpoint 中的暂停标志
    if full_state.get("pause_after_step", False):
        await graph.aupdate_state(
            config,
            {
                "pause_after_step": False,
                "previous_layer": 0,
            }
        )
        logger.info(f"[Planning API] [{session_id}] 已清除 pause_after_step 和 previous_layer 标志")

    # 发送 layer_started 事件（如果是有效的层级）
    # 注意：如果需要修复，不发送 layer_started，因为修复是对当前已完成层级的修改
    need_revision = full_state.get("need_revision", False)
    layer_names = {1: "现状分析", 2: "规划思路", 3: "详细规划"}
    if current_layer in [1, 2, 3] and not need_revision:
        started_event = {
            "type": "layer_started",
            "layer": current_layer,
            "layer_number": current_layer,
            "layer_name": layer_names.get(current_layer, f"Layer {current_layer}"),
            "session_id": session_id,
            "message": f"开始执行 Layer {current_layer}: {layer_names.get(current_layer, '')}",
            "timestamp": datetime.now().isoformat()
        }
        _append_session_event(session_id, started_event)
        logger.info(f"[Planning API] [{session_id}] ✓ 恢复时发送 layer_started 事件: Layer {current_layer}")
    elif need_revision:
        logger.info(f"[Planning API] [{session_id}] 检测到 need_revision=True，跳过 layer_started 事件")

    await _set_stream_state(session_id, "active")

    # 启动后台执行
    asyncio.create_task(
        _execute_graph_in_background(session_id, graph, None, saver)
    )
    
    logger.info(f"[Planning API] [{session_id}] 恢复执行，stream_url=/api/planning/stream/{session_id}")

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
        # ✅ SSOT 简化：只保留 SSE 所需的最小字段，业务状态从 LangGraph Checkpoint 读取
        with _sessions_lock:
            _sessions[session_id] = {
                "session_id": session_id,
                "project_name": request.project_name,
                "created_at": datetime.now().isoformat(),
                "events": deque(maxlen=MAX_SESSION_EVENTS),  # SSE 事件队列（阅后即焚）
            }

        # Mark execution as active (数据库写入)
        await _set_execution_active(session_id, True)

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

    # 🔧 新增：详细的 SSE 连接日志
    session_state = _sessions.get(session_id, {})
    current_layer = session_state.get("current_layer", "?")
    sent_layer_events = session_state.get("sent_layer_events", set())
    stream_state = _stream_states.get(session_id, "unknown")
    subscriber_count_before = len(_session_subscribers.get(session_id, set()))
    
    logger.info(f"[Planning API] [{session_id}] ===== SSE 连接建立 =====")
    logger.info(f"[Planning API] [{session_id}] 连接前状态: current_layer={current_layer}, stream_state={stream_state}")
    logger.info(f"[Planning API] [{session_id}] 已发送的层级事件: {sent_layer_events}")
    logger.info(f"[Planning API] [{session_id}] 连接前订阅者数量: {subscriber_count_before}")

    async def event_generator():
        # 🔧 订阅 session 的 asyncio.Queue（事件驱动模式）
        queue = await subscribe_session(session_id)
        
        try:
            # 立即发送连接成功事件
            yield _format_sse_json({
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
                    yield _format_sse_json(event)

                    # 检查终止事件
                    if event_type in ["completed", "error"]:
                        logger.info(f"[Planning] [{session_id}] SSE 流结束: {event_type}")
                        return
                    elif event_type == "stream_paused":
                        _stream_states[session_id] = "paused"
                        logger.info(f"[Planning] [{session_id}] stream_paused: 发送并关闭连接")
                        return
                        
                except asyncio.TimeoutError:
                    # 30秒无事件，发送心跳保持连接
                    yield ": keep-alive\n\n"

        except asyncio.CancelledError:
            # 🔧 新增：更详细的断开连接日志
            subscriber_count_after = len(_session_subscribers.get(session_id, set()))
            logger.info(f"[Planning] SSE client disconnected: {session_id} (CancelledError)")
            logger.info(f"[Planning] SSE 断开后订阅者数量: {subscriber_count_after}")
        except Exception as e:
            logger.error(f"[Planning] SSE error for {session_id}: {e}", exc_info=True)
            yield _format_sse_json({
                "type": "error",
                "session_id": session_id,
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            })
        except asyncio.CancelledError:
            # 🔧 新增：断开后状态日志
            final_subscriber_count = len(_session_subscribers.get(session_id, set()))
            logger.info(f"[Planning] [{session_id}] SSE 连接已关闭（Cancelled），剩余订阅者: {final_subscriber_count}")
            logger.info(f"[Planning] SSE client disconnected: {session_id}")
        except Exception as e:
            logger.error(f"[Planning] SSE error for {session_id}: {e}", exc_info=True)
            yield _format_sse_json({
                "type": "error",
                "session_id": session_id,
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            })
        finally:
            # 🔧 取消订阅
            final_subscriber_count = len(_session_subscribers.get(session_id, set()))
            logger.info(f"[Planning] [{session_id}] SSE finally: 取消订阅，当前订阅者数: {final_subscriber_count}")
            await unsubscribe_session(session_id, queue)

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

    # 2. 从 LangGraph Checkpoint 获取完整状态
    current_layer = 1
    previous_layer = 0
    layer_1_completed = False
    layer_2_completed = False
    layer_3_completed = False
    pause_after_step = False
    messages = []
    revision_history = []
    analysis_reports = {}
    concept_reports = {}
    detail_reports = {}
    metadata = {}  # 【新增】用于存储版本号等元数据
    version = 0    # 【新增】版本号
    
    try:
        checkpointer = await get_global_checkpointer()
        graph = create_village_planning_graph(checkpointer=checkpointer)
        config = {"configurable": {"thread_id": session_id}}
        checkpoint_state = await graph.aget_state(config)
        
        if checkpoint_state and checkpoint_state.values:
            state = checkpoint_state.values
            
            # 从 Checkpoint 读取所有状态
            current_layer = state.get("current_layer", 1)
            previous_layer = state.get("previous_layer", 0)
            layer_1_completed = state.get("layer_1_completed", False)
            layer_2_completed = state.get("layer_2_completed", False)
            layer_3_completed = state.get("layer_3_completed", False)
            pause_after_step = state.get("pause_after_step", False)
            
            # 提取消息历史
            raw_messages = state.get("messages", [])
            for msg in raw_messages:
                if hasattr(msg, 'content'):
                    messages.append({
                        "type": msg.__class__.__name__.lower().replace("message", ""),
                        "content": msg.content,
                        "role": "assistant" if "ai" in msg.__class__.__name__.lower() else "user"
                    })
            
            revision_history = state.get("revision_history", [])
            analysis_reports = state.get("analysis_reports", {})
            concept_reports = state.get("concept_reports", {})
            detail_reports = state.get("detail_reports", {})
            
            # 【新增】获取版本号用于前端同步
            metadata = state.get("metadata", {})
            version = metadata.get("version", 0)
            
            logger.debug(f"[Status] [{session_id}] Checkpoint: layer={current_layer}, pause={pause_after_step}, version={version}")
    except Exception as e:
        logger.warning(f"[Status] [{session_id}] 获取 Checkpoint 失败: {e}")

    # 3. 计算进度
    progress = None
    if current_layer == 4:
        progress = 100
    elif current_layer in [1, 2, 3]:
        progress = (current_layer / 3) * 100

    # 判断执行完成状态
    execution_complete = layer_1_completed and layer_2_completed and layer_3_completed

    # ✅ 从 checkpoint 配置中获取真实的 checkpoint_id
    last_checkpoint_id = checkpoint_state.config.get("configurable", {}).get("checkpoint_id", "") if checkpoint_state else ""

    return {
        "session_id": session_id,
        # 业务元数据 (来自数据库)
        "status": db_session.get("status", "running"),
        "execution_error": db_session.get("execution_error"),
        "created_at": db_session.get("created_at", ""),
        # 【新增】版本号，用于前端同步
        "version": version,
        # 当前层级和状态 (来自 Checkpoint)
        "current_layer": current_layer,
        "previous_layer": previous_layer,
        "layer_1_completed": layer_1_completed,
        "layer_2_completed": layer_2_completed,
        "layer_3_completed": layer_3_completed,
        "pause_after_step": pause_after_step,
        "execution_complete": execution_complete,
        "progress": progress,
        "last_checkpoint_id": last_checkpoint_id,
        # 消息历史和修订历史
        "messages": messages,
        "revision_history": revision_history,
        # UI 消息列表
        "ui_messages": await get_ui_messages_async(session_id),
        # 维度报告数据
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
    【Signal-Fetch Pattern】从 Checkpoint 获取指定层级的完整维度报告
    
    这个 API 是"单一真实源"的数据拉取端点，前端在收到 SSE layer_completed 信号后，
    调用此 API 获取完整、可靠的维度报告数据，避免 SSE 传输中数据丢失的问题。
    
    Args:
        session_id: 会话 ID
        layer: 层级编号 (1/2/3)
        
    Returns:
        {
            "layer": 1,
            "reports": { "dimension_key": "content", ... },
            "report_content": "合并后的完整报告",
            "project_name": "...",
            "completed": true
        }
    """
    # 验证层级有效
    if layer not in [1, 2, 3]:
        raise HTTPException(status_code=400, detail=f"Invalid layer: {layer}. Must be 1, 2, or 3.")
    
    # 验证 session 存在
    db_session = await get_session_async(session_id)
    if not db_session:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")
    
    try:
        # 从 Checkpoint 获取完整状态
        checkpointer = await get_global_checkpointer()
        graph = create_village_planning_graph(checkpointer=checkpointer)
        config = {"configurable": {"thread_id": session_id}}
        checkpoint_state = await graph.aget_state(config)
        
        if not checkpoint_state or not checkpoint_state.values:
            raise HTTPException(status_code=404, detail=f"No checkpoint found for session: {session_id}")
        
        # 根据层级获取对应的维度报告
        project_name = checkpoint_state.values.get("project_name", "村庄规划")
        
        if layer == 1:
            reports = checkpoint_state.values.get("analysis_reports", {})
            layer_completed = checkpoint_state.values.get("layer_1_completed", False)
            from src.utils.report_utils import generate_analysis_report
            report_content = generate_analysis_report(reports, project_name)
        elif layer == 2:
            reports = checkpoint_state.values.get("concept_reports", {})
            layer_completed = checkpoint_state.values.get("layer_2_completed", False)
            from src.utils.report_utils import generate_concept_report
            report_content = generate_concept_report(reports, project_name)
        else:  # layer == 3
            reports = checkpoint_state.values.get("detail_reports", {})
            layer_completed = checkpoint_state.values.get("layer_3_completed", False)
            from src.utils.report_utils import generate_detail_report
            report_content = generate_detail_report(reports, project_name)
        
        # 计算统计数据
        total_chars = sum(len(v) for v in reports.values()) if reports else 0
        dimension_count = len(reports) if reports else 0
        
        # ✅ 详细日志：追踪每个维度的内容长度
        logger.info(f"[Planning API] [{session_id}] === REST API Layer {layer} 数据 ===")
        logger.info(f"[Planning API] [{session_id}] 维度数量: {dimension_count}, 总字符数: {total_chars}")
        if reports:
            for key, value in reports.items():
                logger.info(f"[Planning API] [{session_id}]   - {key}: {len(value)} chars")
        else:
            logger.warning(f"[Planning API] [{session_id}] ⚠️ reports 为空！")
        
        return {
            "layer": layer,
            "reports": reports,
            "report_content": report_content,
            "project_name": project_name,
            "completed": layer_completed,
            "stats": {
                "dimension_count": dimension_count,
                "total_chars": total_chars
            }
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


@router.post("/api/planning/review/{session_id}")
async def review_action(session_id: str, request: ReviewActionRequest):
    """
    Handle review actions from web frontend
    ✅ SSOT 模式：始终从 Checkpoint 获取状态，不依赖内存
    """
    logger.info(f"🔥🔥🔥 review_action 被调用！ session_id={session_id}")
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

        # ========== 3. ✅ 直接从 Checkpoint 获取状态（不依赖内存 initial_state）==========
        checkpointer = await get_global_checkpointer()
        graph = create_village_planning_graph(checkpointer=checkpointer)
        config = {"configurable": {"thread_id": session_id}}
        
        checkpoint_state = await graph.aget_state(config)
        if not checkpoint_state or not checkpoint_state.values:
            raise HTTPException(status_code=404, detail=f"Session not found in checkpoint: {session_id}")
        
        state = checkpoint_state.values
        review_id = state.get("review_id", "")
        is_pause_mode = state.get("pause_after_step", False)
        
        logger.info(f"[Planning API] [{session_id}] 从 Checkpoint 读取状态:")
        logger.info(f"[Planning API] [{session_id}]   - review_id: {review_id}")
        logger.info(f"[Planning API] [{session_id}]   - pause_after_step: {is_pause_mode}")
        logger.info(f"[Planning API] [{session_id}]   - current_layer: {state.get('current_layer', 1)}")

        if not review_id and not is_pause_mode and request.action != "rollback":
            raise HTTPException(status_code=400, detail="No pending review or pause")

        from src.tools.web_review_tool import WebReviewTool
        web_review_tool = WebReviewTool()

        # ---------- approve ----------
        if request.action == "approve":
            logger.info(f"[Planning API] [{session_id}] 批准请求 - 状态检查")
            logger.info(f"[Planning API] [{session_id}]   - review_id: {review_id}")
            logger.info(f"[Planning API] [{session_id}]   - pause_after_step: {is_pause_mode}")
            logger.info(f"[Planning API] [{session_id}]   - current_layer: {state.get('current_layer', 1)}")

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
            
            # ✅ 优化：后台执行 _resume_graph_execution，立即返回响应
            # 减少前端等待时间（从 100-300ms 降至 < 50ms）
            asyncio.create_task(_resume_graph_execution(session_id))
            
            return {
                "message": "approved",
                "session_id": session_id,
                "resumed": True,
                "current_layer": next_layer,
            }

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

            # ✅ 优化：后台执行 _resume_graph_execution，立即返回响应
            asyncio.create_task(_resume_graph_execution(session_id))

            return {
                "message": "rejected",
                "session_id": session_id,
                "resumed": True,
            }

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

                # 3. 构建配置（使用 session_id 作为 thread_id）
                config = {"configurable": {"thread_id": session_id}}
                logger.info(f"[Rollback] 查找检查点: session_id={session_id}, checkpoint_id={request.checkpoint_id}")

                # 4. 从 LangGraph 检查点历史中查找目标检查点
                target_state_snapshot = None
                available_checkpoints = []
                async for state_snapshot in graph.aget_state_history(config):
                    snapshot_checkpoint_id = state_snapshot.config.get("configurable", {}).get("checkpoint_id", "")
                    available_checkpoints.append(snapshot_checkpoint_id)
                    if snapshot_checkpoint_id == request.checkpoint_id:
                        target_state_snapshot = state_snapshot
                        break

                if not target_state_snapshot:
                    logger.error(f"[Rollback] 检查点未找到! 可用的检查点: {available_checkpoints}")
                    raise HTTPException(
                        status_code=404,
                        detail=f"Checkpoint not found: {request.checkpoint_id}"
                    )

                # 5. 使用 aupdate_state 恢复状态，并设置暂停审查状态
                target_values = target_state_snapshot.values
                
                # 从 metadata 获取检查点信息
                metadata = target_values.get("metadata", {})
                checkpoint_type = metadata.get("checkpoint_type", "regular")
                checkpoint_phase = metadata.get("checkpoint_phase", "")
                checkpoint_layer = metadata.get("checkpoint_layer", 0)
                
                # 检查是否为关键检查点
                if checkpoint_type != "key":
                    # 如果不是关键检查点，回退到旧的判断逻辑
                    logger.warning(f"[Rollback] 检查点类型为 '{checkpoint_type}'，使用回退判断逻辑")
                
                def determine_completed_layer_from_phase(phase: str) -> int:
                    """从阶段枚举值获取层级"""
                    phase_layer_map = {
                        "layer1_completed": 1,
                        "layer2_completed": 2,
                        "layer3_completed": 3,
                        "final_output": 3,
                    }
                    return phase_layer_map.get(phase, 0)
                
                def determine_completed_layer(values: dict) -> int:
                    """
                    综合判断刚完成的层级
                    
                    优先级：
                    1. metadata.checkpoint_phase（如果存在且有效）
                    2. phase 字段（新增的明确阶段标识）
                    3. previous_layer（如果存在且有效）
                    4. layer_N_completed 标志
                    5. 数据存在性判断
                    """
                    # 优先从 metadata 读取
                    meta = values.get("metadata", {})
                    meta_phase = meta.get("checkpoint_phase", "")
                    if meta_phase:
                        layer = determine_completed_layer_from_phase(meta_phase)
                        if layer > 0:
                            logger.info(f"[Rollback] 使用 metadata.checkpoint_phase={meta_phase}，层级={layer}")
                            return layer
                    
                    # 其次使用 phase 字段
                    phase = values.get("phase", "")
                    if phase:
                        layer = determine_completed_layer_from_phase(phase)
                        if layer > 0:
                            logger.info(f"[Rollback] 使用 phase={phase}，层级={layer}")
                            return layer
                    
                    # 回退：使用 previous_layer（如果存在且有效）
                    prev_layer = values.get("previous_layer", 0)
                    if prev_layer > 0:
                        logger.info(f"[Rollback] 使用 previous_layer={prev_layer}")
                        return prev_layer
                    
                    # 回退：根据完成标志判断
                    if values.get("layer_3_completed", False):
                        logger.info("[Rollback] 根据 layer_3_completed=True 判断层级为 3")
                        return 3
                    if values.get("layer_2_completed", False):
                        logger.info("[Rollback] 根据 layer_2_completed=True 判断层级为 2")
                        return 2
                    if values.get("layer_1_completed", False):
                        logger.info("[Rollback] 根据 layer_1_completed=True 判断层级为 1")
                        return 1
                    
                    # 最后回退：根据数据存在判断（检查非空字典）
                    detail_reports = values.get("detail_reports", {})
                    if detail_reports and len(detail_reports) > 0:
                        logger.info(f"[Rollback] 根据 detail_reports 存在判断层级为 3，维度数: {len(detail_reports)}")
                        return 3
                    
                    concept_reports = values.get("concept_reports", {})
                    if concept_reports and len(concept_reports) > 0:
                        logger.info(f"[Rollback] 根据 concept_reports 存在判断层级为 2，维度数: {len(concept_reports)}")
                        return 2
                    
                    analysis_reports = values.get("analysis_reports", {})
                    if analysis_reports and len(analysis_reports) > 0:
                        logger.info(f"[Rollback] 根据 analysis_reports 存在判断层级为 1，维度数: {len(analysis_reports)}")
                        return 1
                    
                    logger.info("[Rollback] 无法判断层级，返回 0（初始状态）")
                    return 0
                
                target_completed_layer = determine_completed_layer(target_values)
                logger.info(f"[Rollback] 最终判断目标层级: {target_completed_layer}")
                
                # 根据目标层级构造回退状态
                # 确保保留目标层级的数据，清空后续层级的数据
                if target_completed_layer == 3:
                    # 回退到 Layer 3 完成时：保留 L1+L2+L3 数据
                    rollback_state = {
                        **target_values,
                        "phase": "layer3_completed",
                        "current_layer": 4,
                        "previous_layer": 3,
                        "pause_after_step": True,
                    }
                    logger.info(f"[Planning API] 回退到 Layer 3 完成状态")
                elif target_completed_layer == 2:
                    # 回退到 Layer 2 完成时：保留 L1+L2 数据，清空 L3
                    rollback_state = {
                        **target_values,
                        # 确保 Layer 2 数据存在
                        "concept_reports": target_values.get("concept_reports", {}),
                        "layer_2_completed": True,
                        "phase": "layer2_completed",
                        # 清空 Layer 3 数据
                        "detail_reports": {},
                        "layer_3_completed": False,
                        # 设置正确的层级状态
                        "current_layer": 3,
                        "previous_layer": 2,
                        "pause_after_step": True,
                    }
                    # 更新 completed_dimensions
                    existing_completed = target_values.get("completed_dimensions", {})
                    rollback_state["completed_dimensions"] = {k: v for k, v in existing_completed.items() if k != "layer3"}
                    logger.info(f"[Planning API] 回退到 Layer 2 完成状态，保留 concept_reports，清空 detail_reports")
                elif target_completed_layer == 1:
                    # 回退到 Layer 1 完成时：仅保留 L1 数据
                    rollback_state = {
                        **target_values,
                        # 确保 Layer 1 数据存在
                        "analysis_reports": target_values.get("analysis_reports", {}),
                        "layer_1_completed": True,
                        "phase": "layer1_completed",
                        # 清空 Layer 2/3 数据
                        "concept_reports": {},
                        "detail_reports": {},
                        "layer_2_completed": False,
                        "layer_3_completed": False,
                        # 设置正确的层级状态
                        "current_layer": 2,
                        "previous_layer": 1,
                        "pause_after_step": True,
                    }
                    # 更新 completed_dimensions
                    existing_completed = target_values.get("completed_dimensions", {})
                    rollback_state["completed_dimensions"] = {"layer1": existing_completed.get("layer1", [])}
                    logger.info(f"[Planning API] 回退到 Layer 1 完成状态，保留 analysis_reports，清空 concept_reports 和 detail_reports")
                else:
                    # 其他情况（初始状态或未知），直接使用检查点值
                    rollback_state = {
                        **target_values,
                        "phase": "init",
                        "pause_after_step": True,
                    }
                    logger.info(f"[Planning API] 回退到初始状态/未知状态，直接使用检查点值")
                
                await graph.aupdate_state(
                    config,
                    rollback_state,
                    as_node=None  # 不指定节点，直接覆盖状态
                )

                logger.info(f"[Planning API] Successfully rolled back to checkpoint {request.checkpoint_id}")

                # 6. 更新 session 元数据（不更新 initial_state，Checkpoint 是唯一数据源）
                session["current_layer"] = rollback_state.get("current_layer", 1)
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

                logger.info(f"[Planning API] Rolling back session {session_id} to Layer {target_completed_layer} completed state")

                return {
                    "message": f"Rolled back to Layer {target_completed_layer} completed state",
                    "current_layer": rollback_state.get("current_layer", 1),
                    "previous_layer": target_completed_layer,
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
    Delete a session completely

    Removes session from:
    1. Memory (_sessions, _active_executions, _stream_states)
    2. Database (planning_sessions table)
    3. UI messages (ui_messages table)
    4. LangGraph checkpoints
    """
    try:
        # 获取 session 信息（用于删除 checkpoint）
        session_info = _sessions.get(session_id)
        project_name = session_info.get("project_name") if session_info else None

        # 1. 删除内存状态
        if session_id in _sessions:
            del _sessions[session_id]

        if session_id in _active_executions:
            del _active_executions[session_id]

        if session_id in _stream_states:
            del _stream_states[session_id]

        # 2. 删除数据库记录
        db_deleted = await delete_session_async(session_id)
        if db_deleted:
            logger.info(f"[Planning API] Deleted database record for session {session_id}")
        else:
            logger.warning(f"[Planning API] No database record found for session {session_id}")

        # 3. 删除 UI 消息
        await delete_ui_messages_async(session_id)
        logger.info(f"[Planning API] Deleted UI messages for session {session_id}")

        # 4. 删除 LangGraph checkpoint（如果有 project_name）
        if project_name:
            try:
                checkpointer = await get_global_checkpointer()
                config = {"configurable": {"thread_id": project_name}}

                # 遍历并删除该 thread_id 下的所有 checkpoint
                deleted_checkpoints = []
                async for state_snapshot in checkpointer.aget_state_history(config):
                    checkpoint_id = state_snapshot.config.get("configurable", {}).get("checkpoint_id")
                    if checkpoint_id:
                        try:
                            await checkpointer.adelete(state_snapshot.config)
                            deleted_checkpoints.append(checkpoint_id)
                        except Exception as e:
                            logger.warning(f"[Planning API] Failed to delete checkpoint {checkpoint_id}: {e}")

                if deleted_checkpoints:
                    logger.info(f"[Planning API] Deleted {len(deleted_checkpoints)} checkpoints for session {session_id}")
            except Exception as e:
                logger.warning(f"[Planning API] Failed to delete checkpoints: {e}")

        logger.info(f"[Planning API] Session {session_id} fully deleted")

        return {"message": f"Session {session_id} deleted", "deleted_checkpoints": project_name is not None}

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

        # ✅ SSOT 简化：只保留 SSE 所需的最小字段
        with _sessions_lock:
            _sessions[session_id] = {
                "session_id": session_id,
                "project_name": request.project_name,
                "created_at": datetime.now().isoformat(),
                "events": deque(maxlen=MAX_SESSION_EVENTS),  # SSE 事件队列
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
        session_id: 会话 ID（推荐传入，确保与 rollback 使用相同的 thread_id）
    """
    try:
        checkpointer = await get_global_checkpointer()
        graph = create_village_planning_graph(checkpointer=checkpointer)

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
            graph = create_village_planning_graph(checkpointer=checkpointer)
            config = {"configurable": {"thread_id": session_id}}
            checkpoint_state = await graph.aget_state(config)
            if checkpoint_state and checkpoint_state.values:
                initial_state = dict(checkpoint_state.values)
                logger.info(f"[Planning API] [{session_id}] 从 Checkpoint 恢复状态成功")
    except Exception as e:
        logger.warning(f"[Planning API] [{session_id}] Checkpoint 读取失败: {e}")

    # ✅ 初始化内存会话，包含完整状态
    with _sessions_lock:
        _sessions[session_id] = {
            "session_id": db_session["session_id"],
            "project_name": db_session["project_name"],
            "created_at": db_session["created_at"].isoformat() if isinstance(db_session["created_at"], datetime) else db_session["created_at"],
            "events": deque(maxlen=MAX_SESSION_EVENTS),  # SSE 事件队列
            "initial_state": initial_state,  # ✅ 添加完整状态
        }
    
    logger.info(f"[Planning API] [{session_id}] 已从数据库重建内存会话（包含 initial_state）")
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
        graph = create_village_planning_graph(checkpointer=checkpointer)
        config = {"configurable": {"thread_id": session_id}}
        checkpoint_state = await graph.aget_state(config)
        
        if not checkpoint_state or not checkpoint_state.values:
            raise HTTPException(status_code=404, detail=f"No checkpoint found for session: {session_id}")
        
        # 获取维度所在层级
        layer = get_dimension_layer(dimension_key)
        if not layer:
            raise HTTPException(status_code=400, detail=f"Unknown dimension: {dimension_key}")
        
        # 根据层级获取对应的报告字典
        if layer == 1:
            reports = checkpoint_state.values.get("analysis_reports", {})
        elif layer == 2:
            reports = checkpoint_state.values.get("concept_reports", {})
        else:
            reports = checkpoint_state.values.get("detail_reports", {})
        
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
