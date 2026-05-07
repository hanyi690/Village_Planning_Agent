"""
SSE Manager - Server-Sent Events Connection Management

This service manages SSE connections and event publishing.
Provides thread-safe event distribution to multiple subscribers.

Centralized state management for:
- Session events (_sessions)
- Execution state (_active_executions)
- Stream state (_stream_states)
- Status log tracking (_status_log_tracker)

All state is now consolidated here for SSOT (Single Source of Truth).
"""

import asyncio
import copy
import json
import logging
import threading
from collections import deque
from datetime import datetime
from threading import Lock, RLock
from typing import Any, Dict, List, Optional, Set

from backend.constants.sse_events import SSEEventType
from backend.constants.config import SSE_QUEUE_SIZE, SSE_QUEUE_WAIT_TIMEOUT

logger = logging.getLogger(__name__)


class SSEManager:
    """
    Centralized SSE connection and event management.

    Features:
    - Thread-safe subscriber management
    - Event queue per connection
    - Cross-thread safe event publishing
    - Historical event synchronization
    """

    # ============================================
    # Cache Configuration (unified pattern for critical events)
    # ============================================

    # Cache config: event_type -> (cache_attr, key_field)
    # cache_attr: name of the class attribute storing cached events
    # key_field: field name in event for secondary key (None for session-level cache)
    CACHE_CONFIG = {
        SSEEventType.DIMENSION_START: ("_last_dimension_start", "dimension_key"),
        SSEEventType.DIMENSION_COMPLETE: ("_last_dimension_complete", "dimension_key"),
        SSEEventType.LAYER_COMPLETED: ("_last_layer_completed", "layer"),
        SSEEventType.LAYER_STARTED: ("_last_layer_started", "layer"),
        SSEEventType.RESUMED: ("_last_resumed", None),
    }

    # ============================================
    # Global State (shared across all instances)
    # ============================================

    # In-memory session storage (events deque for each session)
    _sessions: Dict[str, Dict[str, Any]] = {}

    # SSE subscribers: session_id -> set of asyncio.Queue
    _session_subscribers: Dict[str, Set[asyncio.Queue]] = {}

    # Thread safety locks
    _sessions_lock = Lock()
    _subscribers_lock = Lock()

    # Main event loop reference (for cross-thread publishing)
    _main_event_loop: asyncio.AbstractEventLoop = None

    # ============================================
    # Execution State (migrated from planning.py)
    # ============================================

    # Track active executions to prevent duplicate runs
    _active_executions: Dict[str, bool] = {}

    # Track stream states to prevent infinite reconnection
    # session_id -> "active" | "paused" | "completed"
    _stream_states: Dict[str, str] = {}

    # Status query log optimization - track repeated queries to reduce log spam
    # session_id -> {count, last_state, last_log_time}
    _status_log_tracker: Dict[str, Dict[str, Any]] = {}

    # Additional locks for new state
    _active_executions_lock = Lock()
    _stream_states_lock = Lock()
    _status_log_lock = Lock()

    # ============================================
    # Pending Events (queue-full fallback cache)
    # ============================================

    # Events waiting to be sent when queue was full: session_id -> list of events
    _pending_events: Dict[str, List[Dict[str, Any]]] = {}
    _pending_events_lock = Lock()

    # ============================================
    # Sequence Numbers (event ordering & dedup)
    # ============================================

    # Global sequence number per session: session_id -> current_seq
    _session_seq: Dict[str, int] = {}
    _session_seq_lock = Lock()

    # Recent events buffer for reconnection sync: session_id -> deque of events
    MAX_SEQ_BUFFER = 50
    _seq_buffer: Dict[str, deque] = {}
    _seq_buffer_lock = Lock()

    # ============================================
    # Critical Event Cache (prevent event loss when no subscribers)
    # ============================================

    # Cache dimension_complete events: session_id -> dimension_key -> event
    _last_dimension_complete: Dict[str, Dict[str, Dict[str, Any]]] = {}

    # Cache dimension_start events: session_id -> dimension_key -> event
    _last_dimension_start: Dict[str, Dict[str, Dict[str, Any]]] = {}

    # Cache layer_completed events: session_id -> layer -> event
    _last_layer_completed: Dict[str, Dict[int, Dict[str, Any]]] = {}

    # Cache layer_started events: session_id -> layer -> event
    _last_layer_started: Dict[str, Dict[int, Dict[str, Any]]] = {}

    # Cache resumed events: session_id -> event
    _last_resumed: Dict[str, Dict[str, Any]] = {}

    # Unified RLock for all cache operations (prevents deadlock from lock ordering issues)
    # RLock allows same thread to acquire lock multiple times without blocking
    _cache_lock = RLock()

    # Legacy lock aliases for gradual migration (all point to same RLock)
    _dimension_cache_lock = _cache_lock
    _dimension_start_cache_lock = _cache_lock
    _layer_cache_lock = _cache_lock
    _layer_started_cache_lock = _cache_lock
    _resumed_cache_lock = _cache_lock

    @classmethod
    def save_event_loop(cls, loop: asyncio.AbstractEventLoop) -> None:
        """
        Save the main event loop reference for cross-thread publishing.

        Should be called during application startup.
        """
        cls._main_event_loop = loop
        logger.info("[SSEManager] Main event loop saved, cross-thread publishing enabled")

    # ============================================
    # Sequence Number Methods
    # ============================================

    @classmethod
    def _get_next_seq(cls, session_id: str) -> int:
        """
        Get next sequence number for a session.

        Thread-safe increment of sequence number.

        Args:
            session_id: Session identifier

        Returns:
            New sequence number
        """
        with cls._session_seq_lock:
            cls._session_seq[session_id] = cls._session_seq.get(session_id, 0) + 1
            return cls._session_seq[session_id]

    @classmethod
    def get_last_seq(cls, session_id: str) -> int:
        """
        Get last sequence number for a session.

        Args:
            session_id: Session identifier

        Returns:
            Last sequence number (0 if not found)
        """
        with cls._session_seq_lock:
            return cls._session_seq.get(session_id, 0)

    @classmethod
    def _add_to_seq_buffer(cls, session_id: str, event: Dict[str, Any]) -> None:
        """
        Add event to sequence buffer for reconnection sync.

        Args:
            session_id: Session identifier
            event: Event dictionary (must contain 'seq' field)
        """
        with cls._seq_buffer_lock:
            if session_id not in cls._seq_buffer:
                cls._seq_buffer[session_id] = deque(maxlen=cls.MAX_SEQ_BUFFER)
            cls._seq_buffer[session_id].append(event)

    @classmethod
    def get_events_from_seq(cls, session_id: str, from_seq: int) -> List[Dict[str, Any]]:
        """
        Get events from a specific sequence number for reconnection sync.

        Args:
            session_id: Session identifier
            from_seq: Start sequence number (exclusive)

        Returns:
            List of events with seq > from_seq
        """
        with cls._seq_buffer_lock:
            if session_id not in cls._seq_buffer:
                return []
            return [e for e in cls._seq_buffer[session_id] if e.get("seq", 0) > from_seq]

    @classmethod
    def clear_seq_state(cls, session_id: str) -> None:
        """
        Clear sequence number state for a session.

        Args:
            session_id: Session identifier
        """
        with cls._session_seq_lock:
            if session_id in cls._session_seq:
                del cls._session_seq[session_id]
        with cls._seq_buffer_lock:
            if session_id in cls._seq_buffer:
                del cls._seq_buffer[session_id]

    # ============================================
    # Unified Cache Operations (using CACHE_CONFIG pattern)
    # ============================================

    @classmethod
    def _get_cache_attr(cls, event_type: str) -> str:
        """Get cache attribute name for event type."""
        config = cls.CACHE_CONFIG.get(event_type)
        return config[0] if config else None

    @classmethod
    def _get_key_field(cls, event_type: str) -> Optional[str]:
        """Get key field name for event type (None for session-level cache)."""
        config = cls.CACHE_CONFIG.get(event_type)
        return config[1] if config else None

    @classmethod
    def _cache_event(cls, session_id: str, event: Dict[str, Any]) -> bool:
        """
        Cache event using unified pattern.

        Args:
            session_id: Session identifier
            event: Event dictionary

        Returns:
            True if event was cached, False if event type not configured
        """
        event_type = event.get("type", "unknown")
        cache_attr = cls._get_cache_attr(event_type)
        if not cache_attr:
            return False

        key_field = cls._get_key_field(event_type)
        cache_dict = getattr(cls, cache_attr, None)
        if cache_dict is None:
            return False

        with cls._cache_lock:
            if session_id not in cache_dict:
                cache_dict[session_id] = {} if key_field else None

            if key_field:
                key_value = event.get(key_field, "")
                if key_value:
                    cache_dict[session_id][key_value] = event
                    logger.info(f"[SSEManager] Cached {event_type} for {session_id}/{key_value}")
            else:
                cache_dict[session_id] = event
                logger.info(f"[SSEManager] Cached {event_type} for {session_id}")

        return True

    @classmethod
    def _sync_cache_to_queue(cls, session_id: str, event_type: str, queue: asyncio.Queue) -> int:
        """
        Sync cached events of a type to queue.

        Args:
            session_id: Session identifier
            event_type: Event type to sync
            queue: Target queue

        Returns:
            Number of events synced
        """
        cache_attr = cls._get_cache_attr(event_type)
        if not cache_attr:
            return 0

        cache_dict = getattr(cls, cache_attr, None)
        if cache_dict is None or session_id not in cache_dict:
            return 0

        synced = 0
        with cls._cache_lock:
            cached_data = cache_dict[session_id]
            if cls._get_key_field(event_type):
                # Keyed cache: iterate over key-value pairs
                for key, event in cached_data.items():
                    try:
                        queue.put_nowait(event)
                        synced += 1
                    except asyncio.QueueFull:
                        logger.warning(f"[SSEManager] Session {session_id}: Queue full, dropping cached {event_type}")
                        break
            else:
                # Session-level cache: single event
                try:
                    queue.put_nowait(cached_data)
                    synced += 1
                except asyncio.QueueFull:
                    logger.warning(f"[SSEManager] Session {session_id}: Queue full, dropping cached {event_type}")

        return synced

    @classmethod
    def _clear_cache_for_session(cls, session_id: str, event_type: str) -> bool:
        """
        Clear cached events for a session.

        Args:
            session_id: Session identifier
            event_type: Event type to clear

        Returns:
            True if cache was cleared, False if not found
        """
        cache_attr = cls._get_cache_attr(event_type)
        if not cache_attr:
            return False

        cache_dict = getattr(cls, cache_attr, None)
        if cache_dict is None:
            return False

        with cls._cache_lock:
            if session_id in cache_dict:
                del cache_dict[session_id]
                return True
        return False

    @classmethod
    def clear_dimension_cache(cls, session_id: str) -> int:
        """
        Clear dimension_complete cache for a session.
        Called when a new layer starts to prevent stale events.

        Args:
            session_id: Session identifier

        Returns:
            Number of cached dimensions cleared
        """
        with cls._cache_lock:
            if session_id in cls._last_dimension_complete:
                count = len(cls._last_dimension_complete[session_id])
                del cls._last_dimension_complete[session_id]
                logger.info(f"[SSEManager] Cleared {count} dimension_complete caches for {session_id}")
                return count
        return 0

    @classmethod
    def clear_dimension_start_cache(cls, session_id: str) -> int:
        """
        Clear dimension_start cache for a session.
        Called when a new layer starts to prevent stale events.

        Args:
            session_id: Session identifier

        Returns:
            Number of cached dimension_start events cleared
        """
        with cls._cache_lock:
            if session_id in cls._last_dimension_start:
                count = len(cls._last_dimension_start[session_id])
                del cls._last_dimension_start[session_id]
                logger.info(f"[SSEManager] Cleared {count} dimension_start caches for {session_id}")
                return count
        return 0

    @classmethod
    def clear_layer_started_cache(cls, session_id: str, exclude_layer: int = None) -> int:
        """
        Clear layer_started cache for a session, excluding a specific layer.

        Called when a new layer starts to prevent stale events from previous layers
        being sent on SSE reconnect.

        Args:
            session_id: Session identifier
            exclude_layer: Layer number to keep (current layer), None to clear all

        Returns:
            Number of cached layer_started events cleared
        """
        with cls._layer_started_cache_lock:
            if session_id not in cls._last_layer_started:
                return 0
            cache = cls._last_layer_started[session_id]
            to_remove = [l for l in cache.keys() if l != exclude_layer]
            for l in to_remove:
                del cache[l]
            if to_remove:
                logger.info(f"[SSEManager] Cleared {len(to_remove)} layer_started caches for {session_id}, keeping Layer {exclude_layer}")
            return len(to_remove)

    @classmethod
    def clear_layer_completed_cache(cls, session_id: str, exclude_layer: int = None) -> int:
        """
        Clear layer_completed cache for a session, excluding a specific layer.

        Called when a new layer starts to prevent stale events from previous layers
        being sent on SSE reconnect.

        Args:
            session_id: Session identifier
            exclude_layer: Layer number to keep (current layer), None to clear all

        Returns:
            Number of cached layer_completed events cleared
        """
        with cls._layer_cache_lock:
            if session_id not in cls._last_layer_completed:
                return 0
            cache = cls._last_layer_completed[session_id]
            to_remove = [l for l in cache.keys() if l != exclude_layer]
            for l in to_remove:
                del cache[l]
            if to_remove:
                logger.info(f"[SSEManager] Cleared {len(to_remove)} layer_completed caches for {session_id}, keeping Layer {exclude_layer}")
            return len(to_remove)

    @classmethod
    def get_session_events(cls, session_id: str) -> deque:
        """
        Get or create events deque for a session.

        Args:
            session_id: Session identifier

        Returns:
            deque for storing events
        """
        with cls._sessions_lock:
            if session_id not in cls._sessions:
                cls._sessions[session_id] = {
                    "events": deque(maxlen=500),
                    "created_at": datetime.now().isoformat(),
                }
            return cls._sessions[session_id].get("events", deque(maxlen=500))

    @classmethod
    def append_event(cls, session_id: str, event: Dict[str, Any]) -> int:
        """
        Append event to session's event deque.

        Args:
            session_id: Session identifier
            event: Event dictionary

        Returns:
            Number of events in the deque after append
        """
        events = cls.get_session_events(session_id)
        with cls._sessions_lock:
            events.append(event)
            return len(events)

    @classmethod
    def get_events_copy(cls, session_id: str) -> list:
        """
        Get deep copy of session events (thread-safe).

        Args:
            session_id: Session identifier

        Returns:
            Deep copy of events list
        """
        with cls._sessions_lock:
            if session_id not in cls._sessions:
                return []
            return copy.deepcopy(list(cls._sessions[session_id].get("events", [])))

    @classmethod
    def clear_session(cls, session_id: str) -> bool:
        """
        Clear session data.

        Args:
            session_id: Session identifier

        Returns:
            True if session was cleared, False if not found
        """
        with cls._sessions_lock:
            if session_id in cls._sessions:
                del cls._sessions[session_id]
                return True
            return False

    @classmethod
    async def subscribe(cls, session_id: str) -> asyncio.Queue:
        """
        Subscribe to session's event stream.

        Creates a dedicated queue for this connection and syncs:
        1. Historical events from session storage
        2. Cached critical events (dimension_complete, layer_completed)

        Args:
            session_id: Session identifier

        Returns:
            asyncio.Queue for this connection
        """
        queue = asyncio.Queue(maxsize=SSE_QUEUE_SIZE)

        with cls._subscribers_lock:
            if session_id not in cls._session_subscribers:
                cls._session_subscribers[session_id] = set()
            cls._session_subscribers[session_id].add(queue)

        # Flush pending events that were cached due to previous queue-full
        pending_flush_count = 0
        with cls._pending_events_lock:
            if session_id in cls._pending_events:
                pending_events = cls._pending_events[session_id]
                for event in pending_events:
                    try:
                        queue.put_nowait(event)
                        pending_flush_count += 1
                    except asyncio.QueueFull:
                        # Queue still full, keep remaining events
                        remaining = pending_events[pending_flush_count:]
                        cls._pending_events[session_id] = remaining
                        logger.warning(
                            f"[SSEManager] Session {session_id}: Queue full on pending flush, "
                            f"{len(remaining)} events still pending"
                        )
                        break
                if pending_flush_count > 0 and len(cls._pending_events.get(session_id, [])) == 0:
                    del cls._pending_events[session_id]
                    logger.info(f"[SSEManager] Session {session_id}: Flushed {pending_flush_count} pending events")

        # ⚠️ 缓存事件优先同步（关键事件优先入队列，防止被大量历史事件挤出）
        # 新同步顺序：layer_started > layer_completed > resumed > dimension_complete > historical

        # 1. cached_layer_started (最高优先级)
        cached_layer_started_count = 0
        with cls._layer_started_cache_lock:
            if session_id in cls._last_layer_started:
                for layer, event in cls._last_layer_started[session_id].items():
                    try:
                        queue.put_nowait(event)
                        cached_layer_started_count += 1
                    except asyncio.QueueFull:
                        logger.warning(f"[SSEManager] Session {session_id}: Queue full, dropping cached layer_started event")
                        break

        # 1.5. cached_dimension_start (after layer_started)
        cached_dimension_start_count = 0
        with cls._dimension_start_cache_lock:
            if session_id in cls._last_dimension_start:
                for dim_key, event in cls._last_dimension_start[session_id].items():
                    try:
                        queue.put_nowait(event)
                        cached_dimension_start_count += 1
                    except asyncio.QueueFull:
                        logger.warning(f"[SSEManager] Session {session_id}: Queue full, dropping cached dimension_start event")
                        break

        # 2. cached_layer_completed
        cached_layer_count = 0
        with cls._layer_cache_lock:
            if session_id in cls._last_layer_completed:
                for layer, event in cls._last_layer_completed[session_id].items():
                    try:
                        queue.put_nowait(event)
                        cached_layer_count += 1
                    except asyncio.QueueFull:
                        logger.warning(f"[SSEManager] Session {session_id}: Queue full, dropping cached layer event")
                        break

        # 3. cached_resumed
        cached_resumed_count = 0
        with cls._resumed_cache_lock:
            if session_id in cls._last_resumed:
                try:
                    queue.put_nowait(cls._last_resumed[session_id])
                    cached_resumed_count += 1
                except asyncio.QueueFull:
                    logger.warning(f"[SSEManager] Session {session_id}: Queue full, dropping cached resumed event")

        # 4. cached_dimension_complete
        cached_dim_count = 0
        with cls._dimension_cache_lock:
            if session_id in cls._last_dimension_complete:
                for dim_key, event in cls._last_dimension_complete[session_id].items():
                    try:
                        queue.put_nowait(event)
                        cached_dim_count += 1
                    except asyncio.QueueFull:
                        logger.warning(f"[SSEManager] Session {session_id}: Queue full, dropping cached dim event")
                        break

        # 5. historical events (最低优先级)
        # 注意：过滤掉终端事件（completed, error），防止历史遗留导致连接立即关闭
        TERMINAL_EVENTS = {"completed", "error"}
        historical_count = 0
        with cls._sessions_lock:
            if session_id in cls._sessions:
                events = cls._sessions[session_id].get("events", [])
                for event in events:
                    # 跳过终端事件，这些不应该在重连时发送
                    if event.get("type") in TERMINAL_EVENTS:
                        continue
                    try:
                        queue.put_nowait(event)
                        historical_count += 1
                    except asyncio.QueueFull:
                        logger.warning(f"[SSEManager] Session {session_id}: Queue full, dropping historical event")
                        break

        total_synced = historical_count + cached_dim_count + cached_dimension_start_count + cached_layer_count + cached_layer_started_count + cached_resumed_count + pending_flush_count
        logger.info(
            f"[SSEManager] Session {session_id}: Subscribed, "
            f"pending_flush={pending_flush_count}, historical={historical_count}, cached_dim_start={cached_dimension_start_count}, cached_dim={cached_dim_count}, cached_layer={cached_layer_count}, "
            f"cached_layer_started={cached_layer_started_count}, cached_resumed={cached_resumed_count}, total={total_synced}"
        )
        return queue

    @classmethod
    async def unsubscribe(cls, session_id: str, queue: asyncio.Queue) -> None:
        """
        Unsubscribe from session's event stream.

        Args:
            session_id: Session identifier
            queue: Queue to remove
        """
        with cls._subscribers_lock:
            if session_id in cls._session_subscribers:
                cls._session_subscribers[session_id].discard(queue)
                if not cls._session_subscribers[session_id]:
                    del cls._session_subscribers[session_id]
                    logger.debug(f"[SSEManager] Session {session_id}: No subscribers, cleaned up")

    @classmethod
    def get_subscriber_count(cls, session_id: str) -> int:
        """
        Get the number of subscribers for a session.

        Args:
            session_id: Session identifier

        Returns:
            Number of active subscribers
        """
        with cls._subscribers_lock:
            return len(cls._session_subscribers.get(session_id, set()))

    @classmethod
    async def wait_for_subscriber(cls, session_id: str, timeout: float = 5.0) -> bool:
        """
        Wait for at least one subscriber to connect.

        This ensures SSE connection is established before streaming starts,
        preventing early dimension_delta events from being lost.

        Args:
            session_id: Session identifier
            timeout: Maximum wait time in seconds (default 5.0)

        Returns:
            True if subscriber connected within timeout, False otherwise

        Note:
            Script mode optimization: If no subscribers after 1s, return early
            to minimize overhead for non-SSE clients.
        """
        start_time = asyncio.get_event_loop().time()
        check_interval = 0.1  # Check every 100ms

        # Early exit optimization: check at 1s if running in script mode
        early_exit_time = 1.0

        while asyncio.get_event_loop().time() - start_time < timeout:
            if cls.get_subscriber_count(session_id) > 0:
                logger.info(f"[SSEManager] Session {session_id}: Subscriber connected after {asyncio.get_event_loop().time() - start_time:.2f}s")
                return True
            await asyncio.sleep(check_interval)

            # Early exit for script mode (no SSE client expected)
            if asyncio.get_event_loop().time() - start_time >= early_exit_time:
                logger.debug(f"[SSEManager] Session {session_id}: No subscriber after 1s, likely script mode")
                # Continue checking for remaining timeout but log less frequently
                check_interval = 0.5  # Slow down checks

        logger.warning(f"[SSEManager] Session {session_id}: No subscriber after {timeout}s timeout, proceeding anyway")
        return False

    @classmethod
    async def publish(cls, session_id: str, event: Dict[str, Any]) -> None:
        """
        Publish event to all subscribers (async version).

        When no subscribers, cache critical events for later delivery.

        Args:
            session_id: Session identifier
            event: Event dictionary
        """
        subscribers = cls._session_subscribers.get(session_id, set())
        event_type = event.get("type", "unknown")

        # Add sequence number to event for ordering and dedup
        seq = cls._get_next_seq(session_id)
        event["seq"] = seq
        event["session_id"] = session_id

        # Add to seq buffer for reconnection sync
        cls._add_to_seq_buffer(session_id, event)

        # Cache critical events regardless of subscriber status
        if event_type == SSEEventType.DIMENSION_START:
            dimension_key = event.get("dimension_key", "")
            if dimension_key:
                with cls._dimension_start_cache_lock:
                    if session_id not in cls._last_dimension_start:
                        cls._last_dimension_start[session_id] = {}
                    cls._last_dimension_start[session_id][dimension_key] = event
                    logger.info(f"[SSEManager] Cached dimension_start for {session_id}/{dimension_key}")

        elif event_type == SSEEventType.DIMENSION_COMPLETE:
            dimension_key = event.get("dimension_key", "")
            if dimension_key:
                with cls._dimension_cache_lock:
                    if session_id not in cls._last_dimension_complete:
                        cls._last_dimension_complete[session_id] = {}
                    cls._last_dimension_complete[session_id][dimension_key] = event
                    logger.info(f"[SSEManager] Cached dimension_complete for {session_id}/{dimension_key}")

        elif event_type == SSEEventType.LAYER_COMPLETED:
            layer = event.get("layer", 0)
            if layer:
                with cls._layer_cache_lock:
                    if session_id not in cls._last_layer_completed:
                        cls._last_layer_completed[session_id] = {}
                    cls._last_layer_completed[session_id][layer] = event
                    logger.info(f"[SSEManager] Cached layer_completed for {session_id}/Layer{layer}")

        elif event_type == SSEEventType.LAYER_STARTED:
            layer = event.get("layer", 0) or event.get("layer_number", 0)
            if layer:
                with cls._layer_started_cache_lock:
                    if session_id not in cls._last_layer_started:
                        cls._last_layer_started[session_id] = {}
                    cls._last_layer_started[session_id][layer] = event
                    logger.info(f"[SSEManager] Cached layer_started for {session_id}/Layer{layer}")

        elif event_type == SSEEventType.RESUMED:
            with cls._resumed_cache_lock:
                cls._last_resumed[session_id] = event
                logger.info(f"[SSEManager] Cached resumed for {session_id}")

        # If no subscribers, skip sending (events are already cached above)
        if not subscribers:
            if event_type in [SSEEventType.DIMENSION_START, SSEEventType.LAYER_COMPLETED, SSEEventType.DIMENSION_COMPLETE, SSEEventType.LAYER_STARTED, SSEEventType.RESUMED]:
                logger.warning(f"[SSEManager] Session {session_id}: No subscribers, event cached")
            return

        success_count = 0
        for queue in list(subscribers):
            try:
                queue.put_nowait(event)
                success_count += 1
            except asyncio.QueueFull:
                # Try blocking wait with timeout before falling back to cache
                try:
                    await asyncio.wait_for(queue.put(event), timeout=SSE_QUEUE_WAIT_TIMEOUT)
                    success_count += 1
                except asyncio.TimeoutError:
                    # Cache to pending_events for later retry
                    with cls._pending_events_lock:
                        cls._pending_events.setdefault(session_id, []).append(event)
                        pending_count = len(cls._pending_events[session_id])
                    logger.warning(
                        f"[SSEManager] Session {session_id}: Queue full after {SSE_QUEUE_WAIT_TIMEOUT}s wait, "
                        f"event cached to pending (total pending: {pending_count})"
                    )

        if event_type in [SSEEventType.LAYER_COMPLETED, SSEEventType.DIMENSION_COMPLETE]:
            logger.info(f"[SSEManager] Session {session_id}: {event_type} sent to {success_count} subscribers")
        else:
            logger.debug(f"[SSEManager] Session {session_id}: {event_type} sent to {success_count} subscribers")

    @classmethod
    def publish_sync(cls, session_id: str, event: Dict[str, Any]) -> None:
        """
        Publish event from synchronous context (cross-thread safe).

        Uses saved main event loop to safely publish from LLM callbacks.

        Args:
            session_id: Session identifier
            event: Event dictionary
        """
        event_type = event.get("type", "unknown")

        loop = cls._main_event_loop
        if loop is None:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                logger.warning(f"[SSEManager] No event loop for {event_type}")
                return

        try:
            asyncio.run_coroutine_threadsafe(
                cls.publish(session_id, event),
                loop
            )
        except Exception as e:
            logger.error(f"[SSEManager] Failed to publish {event_type}: {e}")

    @classmethod
    def format_sse(cls, event: Dict[str, Any]) -> str:
        """
        Format event as SSE data.

        Args:
            event: Event dictionary

        Returns:
            SSE formatted string
        """
        event_type = event.get("type", "message")
        json_str = json.dumps(event, ensure_ascii=False)
        return f"event: {event_type}\ndata: {json_str}\n\n"

    # ============================================
    # Execution State Methods (migrated from planning.py)
    # ============================================

    @classmethod
    def is_execution_active(cls, session_id: str) -> bool:
        """
        Check if execution is active for a session.

        Args:
            session_id: Session identifier

        Returns:
            True if execution is active, False otherwise
        """
        with cls._active_executions_lock:
            return cls._active_executions.get(session_id, False)

    @classmethod
    def set_execution_active(cls, session_id: str, active: bool) -> None:
        """
        Set execution active state for a session.

        Args:
            session_id: Session identifier
            active: Active state to set
        """
        with cls._active_executions_lock:
            cls._active_executions[session_id] = active
            logger.debug(f"[SSEManager] Session {session_id}: execution_active = {active}")

    @classmethod
    def delete_execution_state(cls, session_id: str) -> bool:
        """
        Delete execution state for a session.

        Args:
            session_id: Session identifier

        Returns:
            True if deleted, False if not found
        """
        with cls._active_executions_lock:
            if session_id in cls._active_executions:
                del cls._active_executions[session_id]
                return True
            return False

    # ============================================
    # Stream State Methods
    # ============================================

    @classmethod
    def get_stream_state(cls, session_id: str) -> str:
        """
        Get stream state for a session.

        Args:
            session_id: Session identifier

        Returns:
            Stream state: "active" | "paused" | "completed" | "unknown"
        """
        with cls._stream_states_lock:
            return cls._stream_states.get(session_id, "unknown")

    @classmethod
    def set_stream_state(cls, session_id: str, state: str) -> None:
        """
        Set stream state for a session.

        Args:
            session_id: Session identifier
            state: New stream state ("active" | "paused" | "completed")
        """
        with cls._stream_states_lock:
            cls._stream_states[session_id] = state
            logger.debug(f"[SSEManager] Session {session_id}: stream_state = {state}")

    @classmethod
    def delete_stream_state(cls, session_id: str) -> bool:
        """
        Delete stream state for a session.

        Args:
            session_id: Session identifier

        Returns:
            True if deleted, False if not found
        """
        with cls._stream_states_lock:
            if session_id in cls._stream_states:
                del cls._stream_states[session_id]
                return True
            return False

    # ============================================
    # Status Log Tracker Methods
    # ============================================

    @classmethod
    def get_status_log_tracker(cls, session_id: str) -> Dict[str, Any]:
        """
        Get status log tracker for a session.

        Args:
            session_id: Session identifier

        Returns:
            Tracker dict: {count, last_state, last_log_time} or empty dict
        """
        with cls._status_log_lock:
            return cls._status_log_tracker.get(session_id, {})

    @classmethod
    def set_status_log_tracker(cls, session_id: str, tracker_data: Dict[str, Any]) -> None:
        """
        Set status log tracker for a session.

        Args:
            session_id: Session identifier
            tracker_data: Tracker data to set
        """
        with cls._status_log_lock:
            cls._status_log_tracker[session_id] = tracker_data

    @classmethod
    def delete_status_log_tracker(cls, session_id: str) -> bool:
        """
        Delete status log tracker for a session.

        Args:
            session_id: Session identifier

        Returns:
            True if deleted, False if not found
        """
        with cls._status_log_lock:
            if session_id in cls._status_log_tracker:
                del cls._status_log_tracker[session_id]
                return True
            return False

    # ============================================
    # Session Access Methods (for planning.py compatibility)
    # ============================================

    @classmethod
    def session_exists(cls, session_id: str) -> bool:
        """
        Check if session exists in memory.

        Args:
            session_id: Session identifier

        Returns:
            True if session exists, False otherwise
        """
        with cls._sessions_lock:
            return session_id in cls._sessions

    @classmethod
    def get_session(cls, session_id: str) -> Optional[Dict[str, Any]]:
        """
        Get session data (thread-safe).

        Args:
            session_id: Session identifier

        Returns:
            Session dict or None if not found
        """
        with cls._sessions_lock:
            return cls._sessions.get(session_id)

    @classmethod
    def get_session_value(cls, session_id: str, key: str, default: Any = None) -> Any:
        """
        Get a specific value from session data (thread-safe).

        Args:
            session_id: Session identifier
            key: Key to retrieve
            default: Default value if key not found

        Returns:
            Session value or default
        """
        with cls._sessions_lock:
            session = cls._sessions.get(session_id)
            if session is None:
                return default
            return session.get(key, default)

    @classmethod
    def set_session_value(cls, session_id: str, key: str, value: Any) -> bool:
        """
        Set a specific value in session data (thread-safe).

        Args:
            session_id: Session identifier
            key: Key to set
            value: Value to set

        Returns:
            True if successful, False if session not found
        """
        with cls._sessions_lock:
            session = cls._sessions.get(session_id)
            if session is None:
                return False
            session[key] = value
            return True

    @classmethod
    def init_session(cls, session_id: str, session_data: Dict[str, Any]) -> None:
        """
        Initialize a new session in memory.

        Args:
            session_id: Session identifier
            session_data: Initial session data
        """
        with cls._sessions_lock:
            cls._sessions[session_id] = session_data
            logger.debug(f"[SSEManager] Session {session_id}: initialized")

    @classmethod
    def update_session_timestamp(cls, session_id: str) -> None:
        """
        Update session's updated_at timestamp.

        Args:
            session_id: Session identifier
        """
        with cls._sessions_lock:
            session = cls._sessions.get(session_id)
            if session:
                session["updated_at"] = datetime.now()

    @classmethod
    def get_all_session_ids(cls) -> List[str]:
        """
        Get all session IDs (thread-safe).

        Returns:
            List of session IDs
        """
        with cls._sessions_lock:
            return list(cls._sessions.keys())

    @classmethod
    def get_session_count(cls) -> int:
        """
        Get total session count.

        Returns:
            Number of sessions
        """
        with cls._sessions_lock:
            return len(cls._sessions)

    # ============================================
    # Cleanup Methods
    # ============================================

    @classmethod
    def cleanup_expired_sessions(cls, cutoff_time: datetime) -> Dict[str, int]:
        """
        Clean up expired sessions and orphan states.

        Args:
            cutoff_time: DateTime threshold for expiration

        Returns:
            Dict with cleanup counts for each category
        """
        cleaned = {
            "sessions": 0,
            "executions": 0,
            "streams": 0,
            "log_trackers": 0,
            "dimension_caches": 0,
            "dimension_start_caches": 0,
            "layer_caches": 0,
            "layer_started_caches": 0,
            "resumed_caches": 0,
            "pending_events": 0,
            "seq_states": 0,
            "seq_buffers": 0,
        }

        # Clean expired sessions
        with cls._sessions_lock:
            expired_ids = [
                sid for sid, sdata in cls._sessions.items()
                if sdata.get("updated_at") and sdata["updated_at"] < cutoff_time
            ]
            for sid in expired_ids:
                del cls._sessions[sid]
                cleaned["sessions"] += 1

        # Get current session IDs for orphan check
        current_session_ids = set(cls.get_all_session_ids())

        # Clean orphan executions
        with cls._active_executions_lock:
            orphan_executions = [
                sid for sid in cls._active_executions
                if sid not in current_session_ids
            ]
            for sid in orphan_executions:
                del cls._active_executions[sid]
                cleaned["executions"] += 1

        # Clean orphan stream states
        with cls._stream_states_lock:
            orphan_streams = [
                sid for sid in cls._stream_states
                if sid not in current_session_ids
            ]
            for sid in orphan_streams:
                del cls._stream_states[sid]
                cleaned["streams"] += 1

        # Clean orphan log trackers
        with cls._status_log_lock:
            orphan_trackers = [
                sid for sid in cls._status_log_tracker
                if sid not in current_session_ids
            ]
            for sid in orphan_trackers:
                del cls._status_log_tracker[sid]
                cleaned["log_trackers"] += 1

        # Clean orphan dimension_complete caches
        with cls._dimension_cache_lock:
            orphan_dim_caches = [
                sid for sid in cls._last_dimension_complete
                if sid not in current_session_ids
            ]
            for sid in orphan_dim_caches:
                del cls._last_dimension_complete[sid]
                cleaned["dimension_caches"] += 1

        # Clean orphan dimension_start caches
        with cls._dimension_start_cache_lock:
            orphan_dim_start_caches = [
                sid for sid in cls._last_dimension_start
                if sid not in current_session_ids
            ]
            for sid in orphan_dim_start_caches:
                del cls._last_dimension_start[sid]
                cleaned["dimension_start_caches"] += 1

        # Clean orphan layer_completed caches
        with cls._layer_cache_lock:
            orphan_layer_caches = [
                sid for sid in cls._last_layer_completed
                if sid not in current_session_ids
            ]
            for sid in orphan_layer_caches:
                del cls._last_layer_completed[sid]
                cleaned["layer_caches"] += 1

        # Clean orphan layer_started caches
        with cls._layer_started_cache_lock:
            orphan_layer_started_caches = [
                sid for sid in cls._last_layer_started
                if sid not in current_session_ids
            ]
            for sid in orphan_layer_started_caches:
                del cls._last_layer_started[sid]
                cleaned["layer_started_caches"] += 1

        # Clean orphan resumed caches
        with cls._resumed_cache_lock:
            orphan_resumed_caches = [
                sid for sid in cls._last_resumed
                if sid not in current_session_ids
            ]
            for sid in orphan_resumed_caches:
                del cls._last_resumed[sid]
                cleaned["resumed_caches"] += 1

        # Clean orphan pending events
        with cls._pending_events_lock:
            orphan_pending = [
                sid for sid in cls._pending_events
                if sid not in current_session_ids
            ]
            for sid in orphan_pending:
                del cls._pending_events[sid]
                cleaned["pending_events"] += 1

        # Clean orphan seq states
        with cls._session_seq_lock:
            orphan_seq = [
                sid for sid in cls._session_seq
                if sid not in current_session_ids
            ]
            for sid in orphan_seq:
                del cls._session_seq[sid]
                cleaned["seq_states"] += 1

        with cls._seq_buffer_lock:
            orphan_seq_buffer = [
                sid for sid in cls._seq_buffer
                if sid not in current_session_ids
            ]
            for sid in orphan_seq_buffer:
                del cls._seq_buffer[sid]
                cleaned["seq_buffers"] += 1

        total = sum(cleaned.values())
        if total > 0:
            logger.info(
                f"[SSEManager] Cleanup completed: "
                f"sessions={cleaned['sessions']}, executions={cleaned['executions']}, "
                f"streams={cleaned['streams']}, trackers={cleaned['log_trackers']}, "
                f"dim_caches={cleaned['dimension_caches']}, dim_start_caches={cleaned['dimension_start_caches']}, "
                f"layer_caches={cleaned['layer_caches']}, layer_started_caches={cleaned['layer_started_caches']}, "
                f"resumed_caches={cleaned['resumed_caches']}, pending_events={cleaned['pending_events']}, "
                f"seq_states={cleaned['seq_states']}, seq_buffers={cleaned['seq_buffers']}"
            )

        return cleaned

    @classmethod
    def delete_session_all_states(cls, session_id: str) -> Dict[str, bool]:
        """
        Delete all states for a session (sessions, executions, streams, log_trackers, event caches).

        Args:
            session_id: Session identifier

        Returns:
            Dict with deletion status for each category
        """
        result = {
            "session": cls.clear_session(session_id),
            "execution": cls.delete_execution_state(session_id),
            "stream": cls.delete_stream_state(session_id),
            "log_tracker": cls.delete_status_log_tracker(session_id),
        }

        # Clean up critical event caches
        with cls._dimension_cache_lock:
            if session_id in cls._last_dimension_complete:
                del cls._last_dimension_complete[session_id]
                result["dimension_cache"] = True
            else:
                result["dimension_cache"] = False

        with cls._dimension_start_cache_lock:
            if session_id in cls._last_dimension_start:
                del cls._last_dimension_start[session_id]
                result["dimension_start_cache"] = True
            else:
                result["dimension_start_cache"] = False

        with cls._layer_cache_lock:
            if session_id in cls._last_layer_completed:
                del cls._last_layer_completed[session_id]
                result["layer_cache"] = True
            else:
                result["layer_cache"] = False

        with cls._layer_started_cache_lock:
            if session_id in cls._last_layer_started:
                del cls._last_layer_started[session_id]
                result["layer_started_cache"] = True
            else:
                result["layer_started_cache"] = False

        with cls._resumed_cache_lock:
            if session_id in cls._last_resumed:
                del cls._last_resumed[session_id]
                result["resumed_cache"] = True
            else:
                result["resumed_cache"] = False

        with cls._pending_events_lock:
            if session_id in cls._pending_events:
                del cls._pending_events[session_id]
                result["pending_events"] = True
            else:
                result["pending_events"] = False

        # Clean up seq state
        cls.clear_seq_state(session_id)
        result["seq_state"] = True

        logger.debug(f"[SSEManager] Session {session_id}: all states deleted")
        return result


# Singleton instance for easy import
sse_manager = SSEManager()


__all__ = ["SSEManager", "sse_manager"]