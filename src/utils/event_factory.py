"""
Event Factory - SSE Event Generation Utilities

Provides standardized factory functions for generating SSE events.
Used by orchestration nodes to create events for the state-driven event pipeline.

Architecture:
    Nodes generate events → sse_events field → emit_sse_events node → SSEManager
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from src.orchestration.state import get_layer_name, LAYER_NAMES_BY_NUMBER


def create_layer_completed_event(
    layer: int,
    phase: str,
    reports: Dict[str, Dict[str, str]],
    pause_after_step: bool,
    previous_layer: int = 0,
    session_id: Optional[str] = None,
    knowledge_sources_cache: Optional[Dict[str, List[Dict]]] = None,
) -> Dict[str, Any]:
    """创建层级完成事件

    Args:
        layer: 完成的层级编号 (1-3)
        phase: 当前阶段
        reports: 层级报告字典
        pause_after_step: 是否暂停等待审查
        previous_layer: 刚完成的层级编号（前端依赖此字段）
        session_id: 可选的 session ID
        knowledge_sources_cache: 各维度知识来源缓存

    Returns:
        标准化的 layer_completed 事件字典
    """
    layer_key = f"layer{layer}"
    dimension_reports = reports.get(layer_key, {})

    # Calculate statistics for frontend signal detection
    dimension_count = len(dimension_reports)
    total_chars = sum(len(v) for v in dimension_reports.values()) if dimension_reports else 0
    has_data = dimension_count > 0 and total_chars > 0

    # Extract knowledge sources for dimensions in this layer
    dimension_knowledge_sources: Dict[str, List[Dict]] = {}
    if knowledge_sources_cache:
        dimension_knowledge_sources = {
            dim_key: knowledge_sources_cache[dim_key]
            for dim_key in dimension_reports.keys()
            if dim_key in knowledge_sources_cache
        }

    return {
        "type": "layer_completed",
        "layer": layer,
        "layer_name": get_layer_name(layer),
        "phase": phase,
        "dimension_reports": dimension_reports,
        "dimension_knowledge_sources": dimension_knowledge_sources,
        "has_data": has_data,
        "dimension_count": dimension_count,
        "total_chars": total_chars,
        "pause_after_step": pause_after_step,
        "previous_layer": previous_layer,
        "session_id": session_id,
        "task_id": session_id,
        "timestamp": datetime.now().isoformat(),
    }


def create_pause_event(
    previous_layer: int,
    step_mode: bool,
    session_id: Optional[str] = None,
    checkpoint_id: Optional[str] = None,
) -> Dict[str, Any]:
    """创建暂停事件

    当层级完成且启用 step_mode 时发送，通知前端等待用户审查。

    Note:
        checkpoint_saved 事件由 _trigger_planning_execution 在 checkpoint 持久化后发送，
        此事件不包含 checkpoint_id。前端应依赖 checkpoint_saved 事件创建 checkpoint。

    Args:
        previous_layer: 刚完成的层级编号
        step_mode: 是否启用分步执行模式
        session_id: 可选的 session ID
        checkpoint_id: 不再使用，保留参数兼容性

    Returns:
        标准化的 pause 事件字典
    """
    return {
        "type": "pause",
        "current_layer": previous_layer,
        "checkpoint_id": checkpoint_id,  # 不再 fallback 到 session_id
        "pause_after_step": True,
        "previous_layer": previous_layer,
        "step_mode": step_mode,
        "message": f"Layer {previous_layer} completed, waiting for review",
        "session_id": session_id,
        "task_id": session_id,
        "timestamp": datetime.now().isoformat(),
    }


def create_checkpoint_saved_event(
    checkpoint_id: str,
    layer: int,
    phase: str,
    session_id: str,
    checkpoint_type: str = "key",
    description: Optional[str] = None,
    is_revision: bool = False,
    revised_dimensions: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """创建检查点保存事件

    当层级完成时发送，通知前端创建检查点标记。

    Args:
        checkpoint_id: LangGraph checkpoint ID
        layer: 层级编号
        phase: 当前阶段
        session_id: Session ID
        checkpoint_type: 检查点类型 ('key' 或 'regular')
        description: 可选描述
        is_revision: 是否是修订检查点
        revised_dimensions: 修订的维度列表

    Returns:
        标准化的 checkpoint_saved 事件字典
    """
    event = {
        "type": "checkpoint_saved",
        "checkpoint_id": checkpoint_id,
        "layer": layer,
        "checkpoint_type": checkpoint_type,
        "phase": phase,
        "session_id": session_id,
        "description": description or f"Layer {layer} checkpoint",
        "timestamp": datetime.now().isoformat(),
    }
    if is_revision:
        event["is_revision"] = True
        event["revised_dimensions"] = revised_dimensions or []
        event["description"] = description or f"Revision checkpoint (Layer {layer})"
    return event


def create_revision_completed_event(
    layer: int,
    revised_dimensions: List[str],
    session_id: str,
    previous_layer: Optional[int] = None,
) -> Dict[str, Any]:
    """创建修订完成事件

    当维度修复完成时发送，通知前端修订已完成。

    Args:
        layer: 当前层级编号
        revised_dimensions: 修订的维度列表
        session_id: Session ID
        previous_layer: 前一个层级编号

    Returns:
        标准化的 revision_completed 事件字典
    """
    return {
        "type": "revision_completed",
        "layer": layer,
        "revised_dimensions": revised_dimensions,
        "session_id": session_id,
        "previous_layer": previous_layer or layer,
        "pause_after_step": True,
        "timestamp": datetime.now().isoformat(),
    }


def create_dimension_delta_event(
    layer: int,
    dimension_key: str,
    delta: str,
    accumulated: str,
    session_id: Optional[str] = None,
) -> Dict[str, Any]:
    """创建维度增量事件（流式输出）

    Args:
        layer: 当前层级
        dimension_key: 维度键
        delta: 本次增量文本
        accumulated: 累积文本
        session_id: 可选的 session ID

    Returns:
        标准化的 dimension_delta 事件字典
    """
    return {
        "type": "dimension_delta",
        "layer": layer,
        "dimension_key": dimension_key,
        "delta": delta,
        "accumulated": accumulated,
        "session_id": session_id,
        "timestamp": datetime.now().isoformat(),
    }


def create_layer_started_event(
    layer: int,
    dimension_count: int,
    session_id: Optional[str] = None,
) -> Dict[str, Any]:
    """创建层级开始事件

    Args:
        layer: 开始的层级编号
        dimension_count: 该层级的维度总数
        session_id: 可选的 session ID

    Returns:
        标准化的 layer_started 事件字典

    Note:
        兼容性设计：同时发送 layer 和 layer_number 字段。
        新代码优先使用 layer 字段，layer_number 保留向后兼容。
        SSEManager 使用 event.get("layer") or event.get("layer_number") 回退逻辑。
    """
    return {
        "type": "layer_started",
        "layer": layer,
        "layer_number": layer,
        "layer_name": get_layer_name(layer),
        "dimension_count": dimension_count,
        "message": f"开始执行 Layer {layer}: {get_layer_name(layer)}",
        "session_id": session_id,
        "task_id": session_id,
        "timestamp": datetime.now().isoformat(),
    }


def create_completed_event(
    session_id: str,
    message: str = "Planning completed successfully",
) -> Dict[str, Any]:
    """创建规划完成事件

    Args:
        session_id: Session ID
        message: 完成消息

    Returns:
        标准化的 completed 事件字典
    """
    return {
        "type": "completed",
        "session_id": session_id,
        "message": message,
        "timestamp": datetime.now().isoformat(),
    }


def create_error_event(
    session_id: str,
    error: str,
) -> Dict[str, Any]:
    """创建错误事件

    Args:
        session_id: Session ID
        error: 错误消息

    Returns:
        标准化的 error 事件字典
    """
    return {
        "type": "error",
        "session_id": session_id,
        "error": error,
        "timestamp": datetime.now().isoformat(),
    }


__all__ = [
    "create_layer_completed_event",
    "create_pause_event",
    "create_checkpoint_saved_event",
    "create_revision_completed_event",
    "create_dimension_delta_event",
    "create_layer_started_event",
    "create_completed_event",
    "create_error_event",
]