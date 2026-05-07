"""
SSE Event Listener for Experiment Scripts
实验脚本 SSE 事件监听器

将实验脚本从轮询机制重构为 SSE 事件监听，
实现与前端一致的响应速度。

使用方法:
    listener = SSEEventListener(session_id)
    await listener.connect()
    event = await listener.wait_for_layer_completion(layer=1)
    await listener.disconnect()

关键事件类型 (来自 backend/constants/sse_events.py):
- layer_completed: Layer 完成（包含 layer 编号）
- dimension_complete: 单维度完成
- checkpoint_saved: Checkpoint 保存完成（替代 wait_for_write）
- revision_completed: 修订完成（scenario 脚本使用）
- completed: 全部流程完成
- error: 错误事件

SSE 端点: /api/planning/stream/{session_id}
"""

import asyncio
import json
import logging
import re
from datetime import datetime
from typing import Dict, Any, Optional, Callable, List

import httpx

logger = logging.getLogger(__name__)


class SSEEventListener:
    """
    SSE 事件监听器。

    订阅后端 SSE 流，提供事件驱动的等待机制。
    """

    # 事件类型常量 (与 backend/constants/sse_events.py 对齐)
    EVENT_CONNECTED = "connected"
    EVENT_HEARTBEAT = "heartbeat"
    EVENT_COMPLETED = "completed"
    EVENT_ERROR = "error"
    EVENT_LAYER_STARTED = "layer_started"
    EVENT_LAYER_COMPLETED = "layer_completed"
    EVENT_DIMENSION_START = "dimension_start"
    EVENT_DIMENSION_COMPLETE = "dimension_complete"
    EVENT_CHECKPOINT_SAVED = "checkpoint_saved"
    EVENT_REVISION_COMPLETED = "revision_completed"
    EVENT_PAUSE = "pause"

    def __init__(
        self,
        session_id: str,
        base_url: str = "http://localhost:8000",
        timeout: float = 30.0,
    ):
        """
        初始化 SSE 监听器。

        Args:
            session_id: Session identifier
            base_url: Backend API base URL
            timeout: Connection timeout in seconds
        """
        self.session_id = session_id
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

        # 连接状态
        self._connected = False
        self._client: Optional[httpx.AsyncClient] = None
        self._task: Optional[asyncio.Task] = None

        # 事件队列
        self._events_queue: asyncio.Queue[Dict[str, Any]] = asyncio.Queue()

        # 事件处理器注册
        self._event_handlers: Dict[str, List[Callable]] = {}

        # 最后接收的事件序列号 (用于同步)
        self._last_seq: int = 0

        logger.info(f"[SSEListener] Initialized for session: {session_id}")

    async def connect(self) -> bool:
        """
        建立 SSE 连接。

        Returns:
            True if connection successful, False otherwise
        """
        if self._connected:
            logger.warning("[SSEListener] Already connected")
            return True

        url = f"{self.base_url}/api/planning/stream/{self.session_id}"
        logger.info(f"[SSEListener] Connecting to SSE stream: {url}")

        try:
            self._client = httpx.AsyncClient(timeout=self.timeout)
            self._task = asyncio.create_task(self._consume_stream())
            self._connected = True
            logger.info("[SSEListener] Connection established")
            return True

        except Exception as e:
            logger.error(f"[SSEListener] Connection failed: {e}")
            return False

    async def _consume_stream(self):
        """
        消费 SSE 流，将事件放入队列。

        SSE 事件格式:
        event: <event_type>
        data: <json_data>
        """
        url = f"{self.base_url}/api/planning/stream/{self.session_id}"

        try:
            async with self._client.stream("GET", url) as response:
                if response.status_code != 200:
                    logger.error(f"[SSEListener] SSE stream returned {response.status_code}")
                    return

                buffer = ""
                current_event_type = None

                async for line in response.aiter_lines():
                    line = line.rstrip('\n')

                    if not line:
                        # 空行表示事件结束
                        if buffer and current_event_type:
                            try:
                                data = json.loads(buffer)
                                event = {
                                    "type": current_event_type,
                                    "data": data,
                                    "session_id": self.session_id,
                                    "timestamp": datetime.now().isoformat(),
                                }

                                # 放入队列
                                await self._events_queue.put(event)

                                # 调用注册的处理器
                                await self._dispatch_event(current_event_type, event)

                                logger.debug(
                                    f"[SSEListener] Received event: {current_event_type}"
                                )

                            except json.JSONDecodeError as e:
                                logger.warning(
                                    f"[SSEListener] Failed to parse event data: {e}"
                                )

                        buffer = ""
                        current_event_type = None
                        continue

                    # 解析 SSE 行
                    if line.startswith("event:"):
                        current_event_type = line[6:].strip()
                    elif line.startswith("data:"):
                        buffer = line[5:].strip()

        except asyncio.CancelledError:
            logger.info("[SSEListener] Stream consumption cancelled")
        except Exception as e:
            logger.error(f"[SSEListener] Stream error: {e}")
            # 将错误事件放入队列
            await self._events_queue.put({
                "type": self.EVENT_ERROR,
                "data": {"error": str(e)},
                "session_id": self.session_id,
            })

    async def _dispatch_event(self, event_type: str, event: Dict[str, Any]):
        """
        分发事件到注册的处理器。

        Args:
            event_type: Event type
            event: Full event data
        """
        handlers = self._event_handlers.get(event_type, [])
        for handler in handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(event)
                else:
                    handler(event)
            except Exception as e:
                logger.warning(f"[SSEListener] Handler error: {e}")

    def register_handler(self, event_type: str, handler: Callable):
        """
        注册事件处理器。

        Args:
            event_type: Event type to handle
            handler: Handler function (sync or async)
        """
        if event_type not in self._event_handlers:
            self._event_handlers[event_type] = []
        self._event_handlers[event_type].append(handler)
        logger.debug(f"[SSEListener] Registered handler for {event_type}")

    async def wait_for_event(
        self,
        event_type: str,
        timeout: float = 600,
        filter_func: Optional[Callable[[Dict], bool]] = None,
    ) -> Dict[str, Any]:
        """
        等待特定事件类型。

        Args:
            event_type: Target event type
            timeout: Maximum wait time in seconds
            filter_func: Optional filter function for event data

        Returns:
            Matching event data

        Raises:
            asyncio.TimeoutError: If timeout expires
        """
        logger.info(
            f"[SSEListener] Waiting for event: {event_type} (timeout={timeout}s)"
        )

        start_time = datetime.now()

        while True:
            elapsed = (datetime.now() - start_time).total_seconds()
            if elapsed > timeout:
                raise asyncio.TimeoutError(
                    f"Timeout waiting for event {event_type} after {timeout}s"
                )

            try:
                # 非阻塞检查队列
                event = await asyncio.wait_for(
                    self._events_queue.get(),
                    timeout=min(5, timeout - elapsed),
                )
            except asyncio.TimeoutError:
                # 队列空，继续等待
                continue

            # 检查事件类型
            if event.get("type") != event_type:
                # 不匹配的事件，放回队列尾部
                await self._events_queue.put(event)
                continue

            # 应用过滤器
            if filter_func and not filter_func(event):
                await self._events_queue.put(event)
                continue

            logger.info(
                f"[SSEListener] Received target event: {event_type} "
                f"(elapsed={elapsed:.1f}s)"
            )
            return event

    async def wait_for_layer_completion(
        self,
        layer: int,
        timeout: float = 600,
    ) -> Dict[str, Any]:
        """
        等待指定 layer 完成。

        Args:
            layer: Target layer (1, 2, or 3)
            timeout: Maximum wait time in seconds

        Returns:
            layer_completed event data
        """
        return await self.wait_for_event(
            self.EVENT_LAYER_COMPLETED,
            timeout=timeout,
            filter_func=lambda e: e.get("data", {}).get("layer") == layer,
        )

    async def wait_for_revision_completion(
        self,
        timeout: float = 600,
    ) -> Dict[str, Any]:
        """
        等待 revision 完成 (用于 scenario 脚本)。

        Args:
            timeout: Maximum wait time in seconds

        Returns:
            revision_completed event data
        """
        return await self.wait_for_event(
            self.EVENT_REVISION_COMPLETED,
            timeout=timeout,
        )

    async def wait_for_checkpoint_saved(
        self,
        timeout: float = 30,
    ) -> Dict[str, Any]:
        """
        等待 checkpoint 保存完成。

        用于替代 wait_for_write=True 的轮询。

        Args:
            timeout: Maximum wait time in seconds

        Returns:
            checkpoint_saved event data
        """
        return await self.wait_for_event(
            self.EVENT_CHECKPOINT_SAVED,
            timeout=timeout,
        )

    async def wait_for_all_layers(
        self,
        timeout_per_layer: float = 600,
    ) -> Dict[int, Dict[str, Any]]:
        """
        等待所有 layer 完成。

        Args:
            timeout_per_layer: Timeout for each layer

        Returns:
            {layer: event_data} mapping
        """
        results = {}

        for layer in [1, 2, 3]:
            event = await self.wait_for_layer_completion(
                layer=layer,
                timeout=timeout_per_layer,
            )
            results[layer] = event

        return results

    async def disconnect(self):
        """
        关闭 SSE 连接。
        """
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

        if self._client:
            await self._client.aclose()
            self._client = None

        self._connected = False
        logger.info("[SSEListener] Disconnected")

    @property
    def is_connected(self) -> bool:
        """检查是否已连接"""
        return self._connected


class SSEEventCollector:
    """
    SSE 事件收集器。

    收集所有 SSE 事件用于实验记录。
    """

    def __init__(self, listener: SSEEventListener):
        """
        初始化收集器。

        Args:
            listener: SSEEventListener instance
        """
        self.listener = listener
        self.events: List[Dict[str, Any]] = []

        # 注册通用处理器
        listener.register_handler("*", self._collect_event)

    def _collect_event(self, event: Dict[str, Any]):
        """
        收集所有事件。
        """
        self.events.append(event)

    def get_events_by_type(self, event_type: str) -> List[Dict[str, Any]]:
        """
        获取特定类型的事件。

        Args:
            event_type: Event type

        Returns:
            List of events
        """
        return [e for e in self.events if e.get("type") == event_type]

    def get_layer_events(self) -> Dict[int, List[Dict[str, Any]]]:
        """
        获取按 layer 分组的事件。

        Returns:
            {layer: [events]} mapping
        """
        result = {1: [], 2: [], 3: []}

        for event in self.events:
            layer = event.get("data", {}).get("layer")
            if layer in result:
                result[layer].append(event)

        return result

    def save_events(self, output_path: str):
        """
        保存事件到文件。

        Args:
            output_path: Output file path
        """
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(self.events, f, indent=2, ensure_ascii=False)
        logger.info(f"[SSECollector] Saved {len(self.events)} events to {output_path}")


__all__ = [
    "SSEEventListener",
    "SSEEventCollector",
]