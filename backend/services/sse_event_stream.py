"""
SSE Event Stream Manager for Dimension Reports
SSE 事件流管理器（用于维度报告实时推送）

Features:
- Stream dimension content as it's generated
- Support for dimension-level progress tracking
- Integration with Redis cache for persistence
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

# Type aliases
EventDict = dict[str, Any]
EventList = list[EventDict]


class SSEEventManager:
    """
    SSE 事件管理器

    管理维度报告的流式推送，支持实时内容传输和完成状态通知。
    """

    def __init__(self) -> None:
        self._event_queues: dict[str, EventList] = {}
        self._lock = asyncio.Lock()

    async def emit_dimension_content(
        self,
        session_id: str,
        layer: int,
        dimension_key: str,
        dimension_name: str,
        content: str,
        is_complete: bool = False
    ) -> None:
        """发送维度内容事件"""
        event = {
            "type": "dimension_content",
            "data": {
                "layer": layer,
                "dimension_key": dimension_key,
                "dimension_name": dimension_name,
                "content": content,
                "is_complete": is_complete,
                "timestamp": datetime.now().isoformat()
            }
        }

        await self._add_event(session_id, event)
        logger.debug(f"[SSE] Dimension content: {layer}/{dimension_key} ({len(content)} chars, complete={is_complete})")

    async def emit_dimension_complete(
        self,
        session_id: str,
        layer: int,
        dimension_key: str,
        dimension_name: str,
        full_content: str
    ) -> None:
        """发送维度完成事件"""
        event = {
            "type": "dimension_complete",
            "data": {
                "layer": layer,
                "dimension_key": dimension_key,
                "dimension_name": dimension_name,
                "full_content": full_content,
                "timestamp": datetime.now().isoformat()
            }
        }

        await self._add_event(session_id, event)
        logger.info(f"[SSE] Dimension complete: {layer}/{dimension_key}")

    async def emit_layer_progress(
        self,
        session_id: str,
        layer: int,
        total_dimensions: int,
        completed_dimensions: int
    ) -> None:
        """发送层级进度事件"""
        progress = round(completed_dimensions / total_dimensions * 100, 1) if total_dimensions > 0 else 0
        event = {
            "type": "layer_progress",
            "data": {
                "layer": layer,
                "total": total_dimensions,
                "completed": completed_dimensions,
                "progress": progress,
                "timestamp": datetime.now().isoformat()
            }
        }

        await self._add_event(session_id, event)
        logger.debug(f"[SSE] Layer {layer} progress: {completed_dimensions}/{total_dimensions}")

    async def emit_layer_complete(
        self,
        session_id: str,
        layer: int,
        dimension_count: int
    ) -> None:
        """发送层级完成事件"""
        event = {
            "type": "layer_complete",
            "data": {
                "layer": layer,
                "dimension_count": dimension_count,
                "timestamp": datetime.now().isoformat(),
                "message": f"Layer {layer} completed with {dimension_count} dimensions"
            }
        }

        await self._add_event(session_id, event)
        logger.info(f"[SSE] Layer {layer} complete")

    async def _add_event(self, session_id: str, event: EventDict) -> None:
        """添加事件到队列"""
        async with self._lock:
            if session_id not in self._event_queues:
                self._event_queues[session_id] = []
            self._event_queues[session_id].append(event)

    async def get_events(self, session_id: str, after_index: int = 0) -> EventList:
        """
        获取事件（用于 SSE 流式推送）

        Args:
            session_id: 会话 ID
            after_index: 获取该索引之后的事件

        Returns:
            事件列表
        """
        async with self._lock:
            if session_id not in self._event_queues:
                return []
            events = self._event_queues[session_id]
            return events[after_index:] if after_index < len(events) else []

    async def clear_events(self, session_id: str) -> None:
        """清除会话的事件队列"""
        async with self._lock:
            if session_id in self._event_queues:
                del self._event_queues[session_id]
            logger.debug(f"[SSE] Cleared events for session {session_id}")

    def get_event_count(self, session_id: str) -> int:
        """获取事件数量（同步方法）"""
        return len(self._event_queues.get(session_id, []))


# 全局单例
_sse_manager: SSEEventManager | None = None


def get_sse_manager() -> SSEEventManager:
    """获取 SSE 管理器单例"""
    global _sse_manager
    if _sse_manager is None:
        _sse_manager = SSEEventManager()
    return _sse_manager


# ==========================================
# Helper Functions
# ==========================================

async def stream_dimension_report(
    session_id: str,
    layer: int,
    dimension_key: str,
    dimension_name: str,
    content: str,
    chunk_size: int = 100
) -> None:
    """
    流式发送维度报告

    将长文本分块流式发送到前端，实现打字机效果。
    """
    manager = get_sse_manager()

    for i in range(0, len(content), chunk_size):
        chunk = content[i:i + chunk_size]
        is_last_chunk = (i + chunk_size) >= len(content)

        await manager.emit_dimension_content(
            session_id=session_id,
            layer=layer,
            dimension_key=dimension_key,
            dimension_name=dimension_name,
            content=chunk,
            is_complete=is_last_chunk
        )

        if not is_last_chunk:
            await asyncio.sleep(0.01)

    await manager.emit_dimension_complete(
        session_id=session_id,
        layer=layer,
        dimension_key=dimension_key,
        dimension_name=dimension_name,
        full_content=content
    )


async def save_and_stream_dimension_report(
    session_id: str,
    layer: int,
    dimension_key: str,
    dimension_name: str,
    content: str,
    use_redis: bool = True,
    stream_content: bool = True
) -> None:
    """
    保存到 Redis 并流式发送维度报告
    """
    if use_redis:
        try:
            from backend.services.redis_client import get_redis_client
            redis_client = get_redis_client()

            if redis_client.enabled:
                await redis_client.save_dimension_report(
                    session_id=session_id,
                    layer=layer,
                    dimension_key=dimension_key,
                    dimension_name=dimension_name,
                    content=content
                )
                logger.info(f"[Redis] Saved dimension report: {layer}/{dimension_key}")
        except Exception as e:
            logger.warning(f"[Redis] Failed to save dimension report: {e}")

    if stream_content:
        await stream_dimension_report(
            session_id=session_id,
            layer=layer,
            dimension_key=dimension_key,
            dimension_name=dimension_name,
            content=content
        )


__all__ = [
    "SSEEventManager",
    "get_sse_manager",
    "stream_dimension_report",
    "save_and_stream_dimension_report",
]

