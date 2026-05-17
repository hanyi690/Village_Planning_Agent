"""
SSE Event Listener for Experiment Scripts
实验脚本 SSE 事件监听器

支持两种模式：
1. HTTP SSE 模式：通过 HTTP 连接后端 SSE 流
2. 进程内模式：直接读取 sse_manager 内部队列（无需启动后端服务器）

使用方法:
    # 进程内模式（推荐，无需后端运行）
    listener = InProcessEventListener(session_id)
    await listener.connect()
    event = await listener.wait_for_layer_completion(layer=1)
    await listener.disconnect()

    # HTTP SSE 模式（需要后端运行在 localhost:8000）
    listener = SSEEventListener(session_id)
    await listener.connect()
    event = await listener.wait_for_layer_completion(layer=1)
    await listener.disconnect()
"""

import asyncio
import json
import logging
from datetime import datetime
from typing import Dict, Any, Optional, Callable, List

import httpx

logger = logging.getLogger(__name__)


class SSEEventListener:
    """
    SSE 事件监听器（HTTP SSE 模式）。

    使用按类型分桶存储，避免不匹配事件重复入队。
    """

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
    EVENT_RAG_RESULT = "rag_result"

    BUCKETED_EVENT_TYPES = {
        EVENT_LAYER_COMPLETED,
        EVENT_DIMENSION_COMPLETE,
        EVENT_DIMENSION_START,
        EVENT_LAYER_STARTED,
        EVENT_CHECKPOINT_SAVED,
        EVENT_COMPLETED,
        EVENT_ERROR,
        EVENT_RAG_RESULT,
        EVENT_REVISION_COMPLETED,
    }

    def __init__(
        self,
        session_id: str,
        base_url: str = "http://localhost:8000",
        timeout: float = 30.0,
    ):
        self.session_id = session_id
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

        self._connected = False
        self._client: Optional[httpx.AsyncClient] = None
        self._task: Optional[asyncio.Task] = None

        # 按类型分桶
        self._buckets: Dict[str, asyncio.Queue] = {}
        for evt_type in self.BUCKETED_EVENT_TYPES:
            self._buckets[evt_type] = asyncio.Queue()
        self._generic_queue: asyncio.Queue = asyncio.Queue()

        self._event_handlers: Dict[str, List[Callable]] = {}
        self._stream_error: Optional[str] = None
        self._stream_ended: bool = False

        logger.info(f"[SSEListener] Initialized for session: {session_id}")

    async def connect(self) -> bool:
        if self._connected:
            logger.warning("[SSEListener] Already connected")
            return True

        url = f"{self.base_url}/api/sessions/{self.session_id}/stream"
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
        url = f"{self.base_url}/api/sessions/{self.session_id}/stream"

        try:
            async with self._client.stream("GET", url) as response:
                if response.status_code != 200:
                    err_msg = f"SSE stream returned {response.status_code}"
                    logger.error(f"[SSEListener] {err_msg}")
                    self._stream_error = err_msg
                    self._stream_ended = True
                    await self._buckets["error"].put({
                        "type": "error",
                        "data": {"error": err_msg},
                        "session_id": self.session_id,
                    })
                    return

                buffer = ""
                current_event_type = None

                async for line in response.aiter_lines():
                    line = line.rstrip('\n')

                    if not line:
                        if buffer and current_event_type:
                            try:
                                data = json.loads(buffer)
                                event = {
                                    "type": current_event_type,
                                    "data": data,
                                    "session_id": self.session_id,
                                    "timestamp": datetime.now().isoformat(),
                                }
                                self._dispatch_to_bucket(current_event_type, event)
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

                    if line.startswith("event:"):
                        current_event_type = line[6:].strip()
                    elif line.startswith("data:"):
                        buffer = line[5:].strip()

        except asyncio.CancelledError:
            logger.info("[SSEListener] Stream consumption cancelled")
            return
        except Exception as e:
            err_msg = f"Stream error: {e}"
            logger.error(f"[SSEListener] {err_msg}")
            self._stream_error = err_msg
            self._stream_ended = True
            await self._buckets["error"].put({
                "type": "error",
                "data": {"error": err_msg},
                "session_id": self.session_id,
            })
        finally:
            self._connected = False
            self._stream_ended = True

    def _dispatch_to_bucket(self, event_type: str, event: Dict[str, Any]):
        if event_type in self._buckets:
            self._buckets[event_type].put_nowait(event)
        self._generic_queue.put_nowait(event)

    async def _dispatch_event(self, event_type: str, event: Dict[str, Any]):
        wildcard_handlers = self._event_handlers.get("*", [])
        for handler in wildcard_handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(event)
                else:
                    handler(event)
            except Exception as e:
                logger.warning(f"[SSEListener] Handler error: {e}")

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
        等待特定事件类型（从分桶队列读取，不重新入队）。

        Raises:
            asyncio.TimeoutError
            RuntimeError: SSE stream error
        """
        logger.info(
            f"[SSEListener] Waiting for event: {event_type} (timeout={timeout}s)"
        )

        queue = self._buckets.get(event_type, self._generic_queue)
        deadline = datetime.now().timestamp() + timeout

        while True:
            if self._stream_error:
                raise RuntimeError(f"SSE stream error: {self._stream_error}")
            if self._stream_ended and queue.empty():
                raise RuntimeError(f"SSE stream ended before receiving {event_type}")

            remaining = deadline - datetime.now().timestamp()
            if remaining <= 0:
                raise asyncio.TimeoutError(
                    f"Timeout waiting for event {event_type} after {timeout}s"
                )

            try:
                event = await asyncio.wait_for(queue.get(), timeout=min(2.0, remaining))
            except asyncio.TimeoutError:
                continue

            if filter_func is None or filter_func(event):
                logger.info(f"[SSEListener] Received target event: {event_type}")
                return event

    async def wait_for_any_event(
        self,
        event_types: List[str],
        timeout: float = 600,
        filter_func: Optional[Callable[[Dict], bool]] = None,
    ) -> Dict[str, Any]:
        """并发等待多种事件类型中的任意一个。"""
        async def _wait_one(evt_type):
            return await self.wait_for_event(
                evt_type, timeout=timeout, filter_func=filter_func
            )

        tasks = [asyncio.create_task(_wait_one(t)) for t in event_types]
        try:
            done, pending = await asyncio.wait(
                tasks, return_when=asyncio.FIRST_COMPLETED
            )
            for t in pending:
                t.cancel()
            return await done.pop()
        except asyncio.CancelledError:
            for t in tasks:
                t.cancel()
            raise

    async def wait_for_layer_completion(
        self, layer: int, timeout: float = 600
    ) -> Dict[str, Any]:
        return await self.wait_for_event(
            self.EVENT_LAYER_COMPLETED,
            timeout=timeout,
            filter_func=lambda e: e.get("data", {}).get("layer") == layer,
        )

    async def wait_for_revision_completion(
        self, timeout: float = 600
    ) -> Dict[str, Any]:
        return await self.wait_for_event(
            self.EVENT_REVISION_COMPLETED, timeout=timeout
        )

    async def wait_for_checkpoint_saved(
        self, timeout: float = 30
    ) -> Dict[str, Any]:
        return await self.wait_for_event(
            self.EVENT_CHECKPOINT_SAVED, timeout=timeout
        )

    async def wait_for_all_layers(
        self, timeout_per_layer: float = 600
    ) -> Dict[int, Dict[str, Any]]:
        results = {}
        for layer in [1, 2, 3]:
            event = await self.wait_for_layer_completion(
                layer=layer, timeout=timeout_per_layer
            )
            results[layer] = event
        return results

    async def disconnect(self):
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
        return self._connected


class InProcessEventListener:
    """
    进程内事件监听器。

    直接读取 sse_manager 的内部队列，不需要 HTTP 连接。
    事件格式已标准化，与 SSEEventListener 兼容。
    """

    EVENT_CONNECTED = SSEEventListener.EVENT_CONNECTED
    EVENT_HEARTBEAT = SSEEventListener.EVENT_HEARTBEAT
    EVENT_COMPLETED = SSEEventListener.EVENT_COMPLETED
    EVENT_ERROR = SSEEventListener.EVENT_ERROR
    EVENT_LAYER_STARTED = SSEEventListener.EVENT_LAYER_STARTED
    EVENT_LAYER_COMPLETED = SSEEventListener.EVENT_LAYER_COMPLETED
    EVENT_DIMENSION_START = SSEEventListener.EVENT_DIMENSION_START
    EVENT_DIMENSION_COMPLETE = SSEEventListener.EVENT_DIMENSION_COMPLETE
    EVENT_CHECKPOINT_SAVED = SSEEventListener.EVENT_CHECKPOINT_SAVED
    EVENT_REVISION_COMPLETED = SSEEventListener.EVENT_REVISION_COMPLETED
    EVENT_PAUSE = SSEEventListener.EVENT_PAUSE
    EVENT_RAG_RESULT = SSEEventListener.EVENT_RAG_RESULT

    BUCKETED_EVENT_TYPES = SSEEventListener.BUCKETED_EVENT_TYPES

    def __init__(self, session_id: str):
        self.session_id = session_id
        self._connected = False
        self._queue: Optional[asyncio.Queue] = None
        self._task: Optional[asyncio.Task] = None

        self._buckets: Dict[str, asyncio.Queue] = {}
        for evt_type in self.BUCKETED_EVENT_TYPES:
            self._buckets[evt_type] = asyncio.Queue()
        self._generic_queue: asyncio.Queue = asyncio.Queue()

        self._event_handlers: Dict[str, List[Callable]] = {}
        self._stream_error: Optional[str] = None
        self._stream_ended: bool = False

        logger.info(f"[InProcessListener] Initialized for session: {session_id}")

    async def connect(self) -> bool:
        if self._connected:
            return True

        try:
            from app.services.sse import sse_manager

            self._queue = await sse_manager.subscribe(self.session_id)
            self._task = asyncio.create_task(self._consume_queue())
            self._connected = True
            logger.info("[InProcessListener] Connected to sse_manager queue")
            return True
        except Exception as e:
            logger.error(f"[InProcessListener] Connection failed: {e}")
            return False

    async def _consume_queue(self):
        try:
            while True:
                event_data = await self._queue.get()

                event_type = event_data.get("type", "unknown")
                normalized = {
                    "type": event_type,
                    "data": event_data,
                    "session_id": self.session_id,
                    "timestamp": event_data.get(
                        "timestamp", datetime.now().isoformat()
                    ),
                }

                self._dispatch_to_bucket(event_type, normalized)
                await self._dispatch_event(event_type, normalized)

                if event_type in ("completed", "error"):
                    self._stream_ended = True
                    logger.info(
                        f"[InProcessListener] Terminal event: {event_type}"
                    )
                    break
        except asyncio.CancelledError:
            logger.info("[InProcessListener] Queue consumption cancelled")
        except Exception as e:
            err_msg = f"Queue error: {e}"
            logger.error(f"[InProcessListener] {err_msg}")
            self._stream_error = err_msg
            self._stream_ended = True

    def _dispatch_to_bucket(self, event_type: str, event: Dict[str, Any]):
        if event_type in self._buckets:
            self._buckets[event_type].put_nowait(event)
        self._generic_queue.put_nowait(event)

    async def _dispatch_event(self, event_type: str, event: Dict[str, Any]):
        wildcard_handlers = self._event_handlers.get("*", [])
        for handler in wildcard_handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(event)
                else:
                    handler(event)
            except Exception as e:
                logger.warning(f"[InProcessListener] Handler error: {e}")

        handlers = self._event_handlers.get(event_type, [])
        for handler in handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(event)
                else:
                    handler(event)
            except Exception as e:
                logger.warning(f"[InProcessListener] Handler error: {e}")

    def register_handler(self, event_type: str, handler: Callable):
        if event_type not in self._event_handlers:
            self._event_handlers[event_type] = []
        self._event_handlers[event_type].append(handler)
        logger.debug(f"[InProcessListener] Registered handler for {event_type}")

    async def wait_for_event(
        self,
        event_type: str,
        timeout: float = 600,
        filter_func: Optional[Callable[[Dict], bool]] = None,
    ) -> Dict[str, Any]:
        logger.info(
            f"[InProcessListener] Waiting for event: {event_type} (timeout={timeout}s)"
        )

        queue = self._buckets.get(event_type, self._generic_queue)
        deadline = datetime.now().timestamp() + timeout

        while True:
            if self._stream_error:
                raise RuntimeError(f"Event stream error: {self._stream_error}")

            remaining = deadline - datetime.now().timestamp()
            if remaining <= 0:
                raise asyncio.TimeoutError(
                    f"Timeout waiting for event {event_type} after {timeout}s"
                )

            try:
                event = await asyncio.wait_for(queue.get(), timeout=min(2.0, remaining))
            except asyncio.TimeoutError:
                continue

            if filter_func is None or filter_func(event):
                logger.info(
                    f"[InProcessListener] Received target event: {event_type}"
                )
                return event

    async def wait_for_any_event(
        self,
        event_types: List[str],
        timeout: float = 600,
        filter_func: Optional[Callable[[Dict], bool]] = None,
    ) -> Dict[str, Any]:
        async def _wait_one(evt_type):
            return await self.wait_for_event(
                evt_type, timeout=timeout, filter_func=filter_func
            )

        tasks = [asyncio.create_task(_wait_one(t)) for t in event_types]
        try:
            done, pending = await asyncio.wait(
                tasks, return_when=asyncio.FIRST_COMPLETED
            )
            for t in pending:
                t.cancel()
            return await done.pop()
        except asyncio.CancelledError:
            for t in tasks:
                t.cancel()
            raise

    async def wait_for_layer_completion(
        self, layer: int, timeout: float = 600
    ) -> Dict[str, Any]:
        return await self.wait_for_event(
            self.EVENT_LAYER_COMPLETED,
            timeout=timeout,
            filter_func=lambda e: e.get("data", {}).get("layer") == layer,
        )

    async def wait_for_revision_completion(
        self, timeout: float = 600
    ) -> Dict[str, Any]:
        return await self.wait_for_event(
            self.EVENT_REVISION_COMPLETED, timeout=timeout
        )

    async def wait_for_checkpoint_saved(
        self, timeout: float = 30
    ) -> Dict[str, Any]:
        return await self.wait_for_event(
            self.EVENT_CHECKPOINT_SAVED, timeout=timeout
        )

    async def wait_for_all_layers(
        self, timeout_per_layer: float = 600
    ) -> Dict[int, Dict[str, Any]]:
        results = {}
        for layer in [1, 2, 3]:
            event = await self.wait_for_layer_completion(
                layer=layer, timeout=timeout_per_layer
            )
            results[layer] = event
        return results

    async def disconnect(self):
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

        self._connected = False
        logger.info("[InProcessListener] Disconnected")

    @property
    def is_connected(self) -> bool:
        return self._connected


class SSEEventCollector:
    """SSE 事件收集器。兼容两种监听器。"""

    def __init__(self, listener):
        self.listener = listener
        self.events: List[Dict[str, Any]] = []
        listener.register_handler("*", self._collect_event)

    def _collect_event(self, event: Dict[str, Any]):
        self.events.append(event)

    def get_events_by_type(self, event_type: str) -> List[Dict[str, Any]]:
        return [e for e in self.events if e.get("type") == event_type]

    def get_layer_events(self) -> Dict[int, List[Dict[str, Any]]]:
        result = {1: [], 2: [], 3: []}
        for event in self.events:
            layer = event.get("data", {}).get("layer")
            if layer in result:
                result[layer].append(event)
        return result

    def save_events(self, output_path: str):
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(self.events, f, indent=2, ensure_ascii=False)
        logger.info(
            f"[SSECollector] Saved {len(self.events)} events to {output_path}"
        )


__all__ = [
    "SSEEventListener",
    "InProcessEventListener",
    "SSEEventCollector",
]
