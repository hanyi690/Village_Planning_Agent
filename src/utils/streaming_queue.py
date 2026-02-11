"""
流式队列管理器 (Streaming Queue Manager)

功能：
- 按维度隔离token队列
- 批处理策略（时间窗口或数量阈值）
- 线程安全设计

使用场景：
- LLM token生成 → 批处理 → SSE推送
- 支持维度级独立流式传输
- 提供Token → 前端显示 < 100ms 延迟

Example:
    manager = StreamingQueueManager(
        batch_size=50,
        batch_window=0.1,
        flush_callback=lambda **kwargs: print(f"Flush: {kwargs}")
    )

    # Add tokens
    manager.add_token("economic", "经济发展", 1, "token1", "token1")
    manager.add_token("economic", "经济发展", 1, "token2", "token1token2")

    # Complete dimension
    full_content = manager.complete_dimension("economic", 1)
"""

import asyncio
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from threading import Lock
from typing import Callable, Optional

logger = logging.getLogger(__name__)


@dataclass
class DimensionStream:
    """维度流状态

    跟踪单个维度的流式生成状态
    """
    dimension_key: str
    layer: int
    dimension_name: str = ""
    token_buffer: list[str] = field(default_factory=list)
    accumulated: str = ""
    last_flush: float = 0
    active: bool = False

    def __post_init__(self):
        """初始化时设置last_flush为当前时间"""
        if self.last_flush == 0:
            self.last_flush = time.time()


class StreamingQueueManager:
    """流式队列管理器

    管理多个维度的token流式队列，支持批处理和线程安全操作。

    Attributes:
        batch_size: token数量阈值，达到此数量触发刷新
        batch_window: 时间窗口（秒），超过此时间触发刷新
        flush_callback: 刷新回调函数，接收维度信息
        streams: 活跃的流字典，key为 f"l{layer}_{dimension_key}"
        _lock: 线程安全锁
    """

    def __init__(
        self,
        batch_size: int = 50,        # token数量阈值
        batch_window: float = 0.1,   # 时间窗口（秒）
        flush_callback: Optional[Callable] = None
    ):
        """初始化流式队列管理器

        Args:
            batch_size: 批处理token数量阈值（默认50）
            batch_window: 批处理时间窗口秒数（默认0.1秒 = 100ms）
            flush_callback: 刷新回调函数，签名为:
                (dimension_key, dimension_name, layer, chunk, accumulated) -> None
        """
        self.batch_size = batch_size
        self.batch_window = batch_window
        self.flush_callback = flush_callback
        self.streams: dict[str, DimensionStream] = {}
        self._lock = Lock()
        self._flush_times: dict[str, float] = defaultdict(lambda: time.time())

    def add_token(
        self,
        dimension_key: str,
        dimension_name: str,
        layer: int,
        token: str,
        accumulated: str
    ) -> bool:
        """添加token到队列，返回是否刷新

        Args:
            dimension_key: 维度键（如 "economic", "social"）
            dimension_name: 维度显示名称（如 "经济发展"）
            layer: 层级号（1=分析, 2=概念, 3=详细）
            token: 新生成的token
            accumulated: 累计完整内容

        Returns:
            bool: 是否触发了刷新（true if flushed）
        """
        stream_key = f"l{layer}_{dimension_key}"

        with self._lock:
            if stream_key not in self.streams:
                self.streams[stream_key] = DimensionStream(
                    dimension_key=dimension_key,
                    layer=layer,
                    dimension_name=dimension_name
                )

            stream = self.streams[stream_key]
            stream.accumulated = accumulated
            stream.token_buffer.append(token)
            stream.active = True

            # 检查是否需要刷新
            should_flush = (
                len(stream.token_buffer) >= self.batch_size or
                (time.time() - stream.last_flush) >= self.batch_window
            )

            if should_flush:
                return self._flush_stream(stream_key)

            return False

    def _flush_stream(self, stream_key: str) -> bool:
        """刷新单个流

        Args:
            stream_key: 流键名

        Returns:
            bool: 刷新是否成功
        """
        stream = self.streams.get(stream_key)
        if not stream or not stream.token_buffer:
            return False

        chunk = "".join(stream.token_buffer)
        stream.token_buffer = []
        stream.last_flush = time.time()
        self._flush_times[stream_key] = time.time()

        if self.flush_callback:
            try:
                self.flush_callback(
                    dimension_key=stream.dimension_key,
                    dimension_name=stream.dimension_name,
                    layer=stream.layer,
                    chunk=chunk,
                    accumulated=stream.accumulated
                )
                logger.debug(
                    f"[StreamingQueue] Flushed {stream_key}: "
                    f"{len(chunk)} chars, {len(stream.accumulated)} total"
                )
            except Exception as e:
                logger.error(f"[StreamingQueue] Flush callback error: {e}")

        return True

    def complete_dimension(self, dimension_key: str, layer: int) -> str:
        """标记维度完成，返回完整内容

        Args:
            dimension_key: 维度键
            layer: 层级号

        Returns:
            str: 完整累计内容
        """
        stream_key = f"l{layer}_{dimension_key}"
        stream = self.streams.get(stream_key)

        if stream:
            # 刷新剩余buffer
            self._flush_stream(stream_key)
            stream.active = False
            logger.info(
                f"[StreamingQueue] Completed {stream_key}: "
                f"{len(stream.accumulated)} chars"
            )
            return stream.accumulated

        return ""

    def get_stream_status(self, dimension_key: str, layer: int) -> dict:
        """获取流状态

        Args:
            dimension_key: 维度键
            layer: 层级号

        Returns:
            dict: 包含 active, accumulated, buffer_size 的状态字典
        """
        stream_key = f"l{layer}_{dimension_key}"
        stream = self.streams.get(stream_key)
        if not stream:
            return {"active": False, "accumulated": "", "buffer_size": 0}

        return {
            "active": stream.active,
            "accumulated": stream.accumulated,
            "buffer_size": len(stream.token_buffer),
            "last_flush": stream.last_flush,
        }

    def flush_all(self) -> int:
        """刷新所有活跃流

        Returns:
            int: 刷新的流数量
        """
        count = 0
        with self._lock:
            for stream_key in list(self.streams.keys()):
                if self._flush_stream(stream_key):
                    count += 1
        return count

    def clear(self) -> None:
        """清空所有流（用于测试或重置）"""
        with self._lock:
            self.streams.clear()
            self._flush_times.clear()

    def get_active_streams(self) -> list[str]:
        """获取所有活跃流的键名列表

        Returns:
            list[str]: 活跃流键名列表
        """
        with self._lock:
            return [
                key for key, stream in self.streams.items()
                if stream.active
            ]

    def get_stats(self) -> dict:
        """获取统计信息

        Returns:
            dict: 包含 total_streams, active_streams, total_buffer_size 的统计
        """
        with self._lock:
            active_count = sum(1 for s in self.streams.values() if s.active)
            total_buffer = sum(len(s.token_buffer) for s in self.streams.values())

            return {
                "total_streams": len(self.streams),
                "active_streams": active_count,
                "total_buffer_size": total_buffer,
                "streams": {
                    key: {
                        "active": stream.active,
                        "buffer_size": len(stream.token_buffer),
                        "accumulated_length": len(stream.accumulated),
                    }
                    for key, stream in self.streams.items()
                }
            }


# ============================================
# Async Variant for asyncio contexts
# ============================================

class AsyncStreamingQueueManager:
    """异步流式队列管理器

    与 StreamingQueueManager 功能相同，但使用 asyncio.Lock
    适用于异步上下文
    """

    def __init__(
        self,
        batch_size: int = 50,
        batch_window: float = 0.1,
        flush_callback: Optional[Callable] = None
    ):
        self.batch_size = batch_size
        self.batch_window = batch_window
        self.flush_callback = flush_callback
        self.streams: dict[str, DimensionStream] = {}
        self._lock = asyncio.Lock()

    async def add_token(
        self,
        dimension_key: str,
        dimension_name: str,
        layer: int,
        token: str,
        accumulated: str
    ) -> bool:
        """添加token到队列（异步版本）"""
        stream_key = f"l{layer}_{dimension_key}"

        async with self._lock:
            if stream_key not in self.streams:
                self.streams[stream_key] = DimensionStream(
                    dimension_key=dimension_key,
                    layer=layer,
                    dimension_name=dimension_name
                )

            stream = self.streams[stream_key]
            stream.accumulated = accumulated
            stream.token_buffer.append(token)
            stream.active = True

            should_flush = (
                len(stream.token_buffer) >= self.batch_size or
                (time.time() - stream.last_flush) >= self.batch_window
            )

            if should_flush:
                return await self._flush_stream_async(stream_key)

            return False

    async def _flush_stream_async(self, stream_key: str) -> bool:
        """刷新单个流（异步版本）"""
        stream = self.streams.get(stream_key)
        if not stream or not stream.token_buffer:
            return False

        chunk = "".join(stream.token_buffer)
        stream.token_buffer = []
        stream.last_flush = time.time()

        if self.flush_callback:
            if asyncio.iscoroutinefunction(self.flush_callback):
                await self.flush_callback(
                    dimension_key=stream.dimension_key,
                    dimension_name=stream.dimension_name,
                    layer=stream.layer,
                    chunk=chunk,
                    accumulated=stream.accumulated
                )
            else:
                self.flush_callback(
                    dimension_key=stream.dimension_key,
                    dimension_name=stream.dimension_name,
                    layer=stream.layer,
                    chunk=chunk,
                    accumulated=stream.accumulated
                )

        return True

    async def complete_dimension(self, dimension_key: str, layer: int) -> str:
        """标记维度完成（异步版本）"""
        stream_key = f"l{layer}_{dimension_key}"
        stream = self.streams.get(stream_key)

        if stream:
            await self._flush_stream_async(stream_key)
            stream.active = False
            return stream.accumulated

        return ""

    async def get_stream_status(self, dimension_key: str, layer: int) -> dict:
        """获取流状态（异步版本）"""
        stream_key = f"l{layer}_{dimension_key}"
        stream = self.streams.get(stream_key)
        if not stream:
            return {"active": False, "accumulated": "", "buffer_size": 0}

        return {
            "active": stream.active,
            "accumulated": stream.accumulated,
            "buffer_size": len(stream.token_buffer),
            "last_flush": stream.last_flush,
        }
