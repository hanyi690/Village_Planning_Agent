"""
SSE 事件发布器

统一的 SSE 事件发送逻辑，从 main_graph.py 提取。
支持批量发送事件，配合 Send API 状态驱动模式。

重构说明：
- 直接使用 sse_manager 而不是 planning.py 的别名函数
- 打破循环依赖，可独立使用
"""

from typing import Dict, Any, Optional, Callable, List
from datetime import datetime

from backend.constants.sse_events import SSEEventType
from ..utils.logger import get_logger

logger = get_logger(__name__)

# Lazy import to avoid circular dependency issues at module load time
_sse_manager = None


def _get_sse_manager():
    """Get SSE manager instance (lazy import)."""
    global _sse_manager
    if _sse_manager is None:
        from backend.services.sse_manager import sse_manager
        _sse_manager = sse_manager
    return _sse_manager


def _send_sse_event(session_id: str, event_data: Dict[str, Any]) -> None:
    """
    内部函数：发送 SSE 事件到 sse_manager

    Args:
        session_id: 会话 ID
        event_data: 事件数据（已包含 type 和 timestamp）
    """
    try:
        sse_manager = _get_sse_manager()
        sse_manager.append_event(session_id, event_data)
        sse_manager.publish_sync(session_id, event_data)
    except ImportError:
        logger.debug(f"[SSE] 无法发送事件: backend.services.sse_manager 未导入")
    except Exception as e:
        logger.warning(f"[SSE] 发送事件失败: {e}")


class SSEPublisher:
    """SSE 事件发布器"""

    @staticmethod
    def send_event(session_id: str, event_type: str, **kwargs) -> None:
        """
        发送 SSE 事件

        Args:
            session_id: 会话 ID
            event_type: 事件类型
            **kwargs: 事件数据
        """
        event_data = {
            "type": event_type,
            "timestamp": datetime.now().isoformat(),
            **kwargs
        }
        _send_sse_event(session_id, event_data)

        # Log key event types (avoid high-frequency events like dimension_delta)
        if event_type in [SSEEventType.TOOL_CALL, SSEEventType.TOOL_RESULT, SSEEventType.LAYER_STARTED, SSEEventType.LAYER_COMPLETED]:
            logger.info(f"[SSEPublisher] {session_id}: sent {event_type}")

    @staticmethod
    def send_events_batch(session_id: str, events: List[Dict[str, Any]]) -> None:
        """
        批量发送 SSE 事件

        用于 Send API 状态驱动模式，从 dimension_results 和 sse_events 字段读取。

        Args:
            session_id: 会话 ID
            events: 事件列表
        """
        if not events:
            return

        for event in events:
            # 确保事件有 timestamp
            if "timestamp" not in event:
                event["timestamp"] = datetime.now().isoformat()
            _send_sse_event(session_id, event)

        logger.debug(f"[SSE] 批量发送 {len(events)} 个事件到 session {session_id}")

    @staticmethod
    def send_layer_start(session_id: str, layer: int, layer_name: str, dimension_count: int) -> None:
        """
        Send layer_started event.

        Clears old layer and dimension caches before sending to prevent
        stale events from previous layer being sent on SSE reconnect.

        Args:
            session_id: Session ID
            layer: Layer number (1-3)
            layer_name: Layer display name
            dimension_count: Number of dimensions in this layer
        """
        sse_manager = _get_sse_manager()

        # Clear old layer_started/layer_completed caches (keep current layer)
        cleared_layer_started = sse_manager.clear_layer_started_cache(session_id, exclude_layer=layer)
        if cleared_layer_started > 0:
            logger.info(f"[SSEPublisher] Cleared {cleared_layer_started} layer_started caches before Layer {layer}")

        cleared_layer_completed = sse_manager.clear_layer_completed_cache(session_id, exclude_layer=layer)
        if cleared_layer_completed > 0:
            logger.info(f"[SSEPublisher] Cleared {cleared_layer_completed} layer_completed caches before Layer {layer}")

        # Clear old dimension_complete cache to prevent stale events
        cleared_count = sse_manager.clear_dimension_cache(session_id)
        if cleared_count > 0:
            logger.info(f"[SSEPublisher] Cleared {cleared_count} dimension caches before Layer {layer}")

        # Clear old dimension_start cache to prevent stale events
        cleared_start_count = sse_manager.clear_dimension_start_cache(session_id)
        if cleared_start_count > 0:
            logger.info(f"[SSEPublisher] Cleared {cleared_start_count} dimension_start caches before Layer {layer}")

        SSEPublisher.send_event(
            session_id=session_id,
            event_type=SSEEventType.LAYER_STARTED,
            layer=layer,
            layer_name=layer_name,
            dimension_count=dimension_count
        )

    @staticmethod
    def send_layer_complete(session_id: str, layer: int, layer_name: str,
                            dimension_count: int, total_chars: int) -> None:
        """发送层级完成事件"""
        SSEPublisher.send_event(
            session_id=session_id,
            event_type=SSEEventType.LAYER_COMPLETED,
            layer=layer,
            layer_name=layer_name,
            dimension_count=dimension_count,
            total_chars=total_chars
        )

    @staticmethod
    def send_dimension_start(session_id: str, layer: int, dimension_key: str,
                             dimension_name: str, is_revision: bool = False) -> None:
        """发送维度开始事件"""
        SSEPublisher.send_event(
            session_id=session_id,
            event_type=SSEEventType.DIMENSION_START,
            layer=layer,
            dimension_key=dimension_key,
            dimension_name=dimension_name,
            is_revision=is_revision
        )

    @staticmethod
    def send_dimension_delta(session_id: str, layer: int, dimension_key: str,
                              dimension_name: str, token: str, accumulated: str,
                              is_revision: bool = False) -> None:
        """发送维度增量事件"""
        SSEPublisher.send_event(
            session_id=session_id,
            event_type=SSEEventType.DIMENSION_DELTA,
            layer=layer,
            dimension_key=dimension_key,
            dimension_name=dimension_name,
            delta=token,
            accumulated=accumulated,
            is_revision=is_revision
        )

    @staticmethod
    def send_dimension_complete(session_id: str, layer: int, dimension_key: str,
                                 dimension_name: str, full_content: str,
                                 is_revision: bool = False,
                                 gis_data: Optional[Dict[str, Any]] = None) -> None:
        """发送维度完成事件"""
        event_data = {
            "layer": layer,
            "dimension_key": dimension_key,
            "dimension_name": dimension_name,
            "full_content": full_content,
            "is_revision": is_revision,
        }
        if gis_data:
            event_data["gis_data"] = gis_data

        SSEPublisher.send_event(
            session_id=session_id,
            event_type=SSEEventType.DIMENSION_COMPLETE,
            **event_data
        )
        if gis_data:
            logger.info(f"[SSEPublisher] sent dimension_complete with gis_data for {dimension_key}")

    @staticmethod
    def send_tool_call(session_id: str, tool_name: str, tool_display_name: str,
                       description: str, estimated_time: Optional[float] = None) -> None:
        """
        发送工具调用开始事件

        Args:
            session_id: 会话 ID
            tool_name: 工具名称（内部标识）
            tool_display_name: 工具显示名称（用户可见）
            description: 工具描述
            estimated_time: 预估执行时间（秒）
        """
        SSEPublisher.send_event(
            session_id=session_id,
            event_type=SSEEventType.TOOL_CALL,
            tool_name=tool_name,
            tool_display_name=tool_display_name,
            description=description,
            estimated_time=estimated_time
        )

    @staticmethod
    def send_tool_progress(session_id: str, tool_name: str, stage: str,
                           progress: float, message: str) -> None:
        """
        发送工具执行进度事件

        Args:
            session_id: 会话 ID
            tool_name: 工具名称
            stage: 当前阶段（如 "initializing", "processing", "finalizing"）
            progress: 进度值（0.0 - 1.0）
            message: 进度消息
        """
        SSEPublisher.send_event(
            session_id=session_id,
            event_type=SSEEventType.TOOL_PROGRESS,
            tool_name=tool_name,
            stage=stage,
            progress=progress,
            message=message
        )

    @staticmethod
    def send_tool_result(session_id: str, tool_name: str, status: str,
                         result_preview: Optional[str] = None,
                         error: Optional[str] = None) -> None:
        """
        发送工具执行结果事件

        Args:
            session_id: 会话 ID
            tool_name: 工具名称
            status: 执行状态（"success", "error"）
            result_preview: 结果预览（截断）
            error: 错误信息（如有）
        """
        SSEPublisher.send_event(
            session_id=session_id,
            event_type=SSEEventType.TOOL_RESULT,
            tool_name=tool_name,
            status=status,
            result_preview=result_preview,
            error=error
        )

    @staticmethod
    def create_token_callback(session_id: str, layer: int,
                               dimension_key: str, dimension_name: str,
                               is_revision: bool = False) -> Callable[[str, str], None]:
        """创建 token 回调函数"""
        def on_token(token: str, accumulated: str) -> None:
            SSEPublisher.send_dimension_delta(
                session_id=session_id,
                layer=layer,
                dimension_key=dimension_key,
                dimension_name=dimension_name,
                token=token,
                accumulated=accumulated,
                is_revision=is_revision
            )
        return on_token

    @staticmethod
    def create_progress_callback(session_id: str, tool_name: str) -> Callable[[str, float, str], None]:
        """
        创建工具进度回调函数

        Args:
            session_id: 会话 ID
            tool_name: 工具名称

        Returns:
            回调函数，接受 (stage, progress, message) 参数
        """
        def on_progress(stage: str, progress: float, message: str) -> None:
            SSEPublisher.send_tool_progress(
                session_id=session_id,
                tool_name=tool_name,
                stage=stage,
                progress=progress,
                message=message
            )
        return on_progress


# 便捷函数
def send_layer_event(session_id: str, layer: int, event_type: str, **kwargs) -> None:
    """发送层级相关事件"""
    from src.orchestration.state import get_layer_name
    kwargs.setdefault("layer_name", get_layer_name(layer))
    SSEPublisher.send_event(session_id, event_type, layer=layer, **kwargs)


def append_dimension_complete_event(
    session_id: str,
    layer: int,
    dimension_key: str,
    dimension_name: str,
    content: str
) -> None:
    """
    发送维度完成事件 (兼容接口)

    Args:
        session_id: 会话ID
        layer: 层级编号 (1/2/3)
        dimension_key: 维度键名
        dimension_name: 维度显示名称
        content: 维度分析内容
    """
    SSEPublisher.send_dimension_complete(
        session_id=session_id,
        layer=layer,
        dimension_key=dimension_key,
        dimension_name=dimension_name,
        full_content=content
    )


# 工具事件状态常量
TOOL_STATUS_RUNNING = "running"
TOOL_STATUS_SUCCESS = "success"
TOOL_STATUS_ERROR = "error"


def append_tool_call_event(
    session_id: str,
    tool_name: str,
    tool_display_name: str,
    description: str,
    estimated_time: Optional[float] = None,
    stage: str = "init"
) -> None:
    """
    发送工具调用开始事件 (兼容接口)

    Args:
        session_id: 会话ID
        tool_name: 工具名称（内部标识）
        tool_display_name: 工具显示名称（用户可见）
        description: 工具执行描述
        estimated_time: 预估执行时间（秒）
        stage: 当前阶段名称
    """
    SSEPublisher.send_tool_call(
        session_id=session_id,
        tool_name=tool_name,
        tool_display_name=tool_display_name,
        description=description,
        estimated_time=estimated_time
    )


def append_tool_progress_event(
    session_id: str,
    tool_name: str,
    stage: str,
    progress: float,
    message: str
) -> None:
    """
    发送工具执行进度事件 (兼容接口)

    Args:
        session_id: 会话ID
        tool_name: 工具名称
        stage: 当前阶段名称
        progress: 进度值 (0.0 - 1.0)
        message: 进度消息
    """
    SSEPublisher.send_tool_progress(
        session_id=session_id,
        tool_name=tool_name,
        stage=stage,
        progress=progress,
        message=message
    )


def append_tool_result_event(
    session_id: str,
    tool_name: str,
    status: str,
    summary: str,
    display_hints: Optional[Dict[str, Any]] = None,
    data_preview: Optional[str] = None
) -> None:
    """
    发送工具执行结果事件 (兼容接口)

    Args:
        session_id: 会话ID
        tool_name: 工具名称
        status: 执行状态 ("success" / "error")
        summary: 结果摘要
        display_hints: 前端渲染提示
        data_preview: 数据预览（可选）
    """
    SSEPublisher.send_tool_result(
        session_id=session_id,
        tool_name=tool_name,
        status=status,
        result_preview=data_preview or summary[:200] if summary else None,
        error=None if status == "success" else summary
    )


__all__ = [
    "SSEPublisher",
    "send_layer_event",
    "append_dimension_complete_event",
    "append_tool_call_event",
    "append_tool_progress_event",
    "append_tool_result_event",
    "TOOL_STATUS_RUNNING",
    "TOOL_STATUS_SUCCESS",
    "TOOL_STATUS_ERROR",
]