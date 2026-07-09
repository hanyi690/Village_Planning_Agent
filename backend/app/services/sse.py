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
import json
import logging
import threading
from collections import deque
from datetime import datetime
from threading import Lock, RLock
from typing import Any, Dict, List, Optional, Set

from app.core.events import SSEEventType
from app.core.settings import SSE_QUEUE_SIZE, SSE_QUEUE_WAIT_TIMEOUT

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

    # ⚠️ IMPORTANT: See SSEPublisher docstring for the full checklist when adding new SSE events.
    # Cache config: event_type -> (cache_attr, key_field)
    # cache_attr: name of the class attribute storing cached events
    # key_field: field name in event for secondary key (None for session-level cache)
    CACHE_CONFIG = {
        SSEEventType.DIMENSION_START: ("_last_dimension_start", "dimension_key"),
        SSEEventType.DIMENSION_COMPLETE: ("_last_dimension_complete", "dimension_key"),
        SSEEventType.DIMENSION_ERROR: ("_last_dimension_error", "dimension_key"),
        SSEEventType.RAG_RESULT: ("_last_rag_result", "dimension_key"),
        SSEEventType.RAG_QUERY: ("_last_rag_query", "dimension_key"),
        SSEEventType.LAYER_COMPLETED: ("_last_layer_completed", "layer"),
        SSEEventType.LAYER_STARTED: ("_last_layer_started", "layer"),
        SSEEventType.RESUMED: ("_last_resumed", None),
        SSEEventType.CASCADE_IMPACT: ("_last_cascade_impact", None),
        SSEEventType.CASCADE_COMPLETE: ("_last_cascade_complete", None),
        SSEEventType.GIS_RESULT: ("_last_gis_result", "dimension_key"),
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

    # Cache cascade_impact events: session_id -> event
    _last_cascade_impact: Dict[str, Dict[str, Any]] = {}

    # Cache cascade_complete events: session_id -> event
    _last_cascade_complete: Dict[str, Dict[str, Any]] = {}

    # Cache rag_result events: session_id -> dimension_key -> event
    _last_rag_result: Dict[str, Dict[str, Dict[str, Any]]] = {}

    # Cache dimension_error events: session_id -> dimension_key -> event
    _last_dimension_error: Dict[str, Dict[str, Dict[str, Any]]] = {}

    # Cache rag_query events: session_id -> dimension_key -> event
    _last_rag_query: Dict[str, Dict[str, Dict[str, Any]]] = {}

    # Cache gis_result events: session_id -> dimension_key -> event
    _last_gis_result: Dict[str, Dict[str, Dict[str, Any]]] = {}

    # Delta coalescing index: session_id -> dimension_key -> last delta event in queue
    # Avoids scanning the entire queue on overflow coalescing
    _delta_coalesce_index: Dict[str, Dict[str, Dict[str, Any]]] = {}

    # Unified RLock for all cache operations (prevents deadlock from lock ordering issues)
    # RLock allows same thread to acquire lock multiple times without blocking
    _cache_lock = RLock()

    # Legacy lock aliases for gradual migration (all point to same RLock)
    _dimension_cache_lock = _cache_lock
    _dimension_start_cache_lock = _cache_lock
    _layer_cache_lock = _cache_lock
    _layer_started_cache_lock = _cache_lock
    _resumed_cache_lock = _cache_lock
    _cascade_impact_cache_lock = _cache_lock
    _cascade_complete_cache_lock = _cache_lock

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
    def get_next_seq(cls, session_id: str) -> int:
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
    def _coalesce_delta_in_queue(cls, session_id: str, dimension_key: str, new_event: Dict[str, Any]) -> bool:
        """Coalesce a delta event with the last same-dimension delta using the index.

        Updates the indexed delta's accumulated content with the newer one,
        avoiding queue growth while preserving content continuity.

        Returns True if coalesced, False if no indexed delta found.
        """
        indexed = cls._delta_coalesce_index.get(session_id, {}).get(dimension_key)
        if indexed is None:
            return False

        indexed["accumulated"] = new_event.get("accumulated", "")
        indexed["delta"] = new_event.get("delta", "")
        indexed["seq"] = new_event.get("seq", indexed.get("seq", 0))
        return True

    @classmethod
    def _update_delta_index(cls, session_id: str, dimension_key: str, event: Dict[str, Any]) -> None:
        """Update the delta coalescing index when a delta is successfully queued."""
        if session_id not in cls._delta_coalesce_index:
            cls._delta_coalesce_index[session_id] = {}
        cls._delta_coalesce_index[session_id][dimension_key] = event

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
        Get copy of session events (thread-safe).
        Events are read-only after creation, so shallow copy suffices.

        Args:
            session_id: Session identifier

        Returns:
            Copy of events list
        """
        with cls._sessions_lock:
            if session_id not in cls._sessions:
                return []
            return list(cls._sessions[session_id].get("events", []))

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

        # Cache event sync (priority order: layer state > dimension state > RAG)
        CACHE_SYNC_ORDER = [
            SSEEventType.LAYER_STARTED,
            SSEEventType.DIMENSION_START,
            SSEEventType.LAYER_COMPLETED,
            SSEEventType.RESUMED,
            SSEEventType.CASCADE_IMPACT,
            SSEEventType.CASCADE_COMPLETE,
            SSEEventType.DIMENSION_COMPLETE,
            SSEEventType.RAG_RESULT,
            SSEEventType.GIS_RESULT,
            SSEEventType.DIMENSION_ERROR,
            SSEEventType.RAG_QUERY,
        ]
        cached_total = 0
        for event_type in CACHE_SYNC_ORDER:
            cached_total += cls._sync_cache_to_queue(session_id, event_type, queue)

        # Historical events (lowest priority)
        TERMINAL_EVENTS = {"completed", "error"}
        historical_count = 0
        with cls._sessions_lock:
            if session_id in cls._sessions:
                events = cls._sessions[session_id].get("events", [])
                for event in events:
                    if event.get("type") in TERMINAL_EVENTS:
                        continue
                    try:
                        queue.put_nowait(event)
                        historical_count += 1
                    except asyncio.QueueFull:
                        logger.warning(f"[SSEManager] Session {session_id}: Queue full, dropping historical event")
                        break

        total_synced = historical_count + cached_total + pending_flush_count
        logger.info(
            f"[SSEManager] Session {session_id}: Subscribed, "
            f"pending_flush={pending_flush_count}, historical={historical_count}, "
            f"cached={cached_total}, total={total_synced}"
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
        with cls._subscribers_lock:
            subscribers = list(cls._session_subscribers.get(session_id, set()))
        event_type = event.get("type", "unknown")

        # Create internal copy to avoid mutating caller's dict
        event = dict(event)
        event["seq"] = cls.get_next_seq(session_id)
        event["session_id"] = session_id

        # Add to seq buffer for reconnection sync
        cls._add_to_seq_buffer(session_id, event)

        # Cache critical events using unified CACHE_CONFIG pattern
        cls._cache_event(session_id, event)

        # If no subscribers, skip sending (events are already cached above)
        if not subscribers:
            if event_type in [SSEEventType.DIMENSION_START, SSEEventType.LAYER_COMPLETED, SSEEventType.DIMENSION_COMPLETE, SSEEventType.LAYER_STARTED, SSEEventType.RESUMED, SSEEventType.CASCADE_IMPACT, SSEEventType.CASCADE_COMPLETE]:
                logger.warning(f"[SSEManager] Session {session_id}: No subscribers, event cached")
            return

        # Non-blocking put with delta coalescing on overflow
        for queue in subscribers:
            try:
                queue.put_nowait(event)
                # Update delta index on successful queue
                if event_type == SSEEventType.DIMENSION_DELTA:
                    dim_key = event.get("dimension_key", "")
                    if dim_key:
                        cls._update_delta_index(session_id, dim_key, event)
            except asyncio.QueueFull:
                if event_type == SSEEventType.DIMENSION_DELTA:
                    # Coalesce with the last same-dimension delta via index
                    dim_key = event.get("dimension_key", "")
                    if dim_key and cls._coalesce_delta_in_queue(session_id, dim_key, event):
                        logger.debug(f"[SSEManager] Delta coalesced for {session_id}/{dim_key}")
                    else:
                        logger.debug(f"[SSEManager] Delta dropped for {session_id} (queue full)")
                else:
                    # Non-delta events: buffer for retry (with cap to prevent unbounded growth)
                    MAX_PENDING_PER_SESSION = 100
                    with cls._pending_events_lock:
                        pending = cls._pending_events.setdefault(session_id, [])
                        if len(pending) >= MAX_PENDING_PER_SESSION:
                            pending.pop(0)
                        pending.append(event)
                    logger.warning(f"[SSEManager] Queue full for session {session_id}, {event_type} buffered")

        if event_type in [SSEEventType.LAYER_COMPLETED, SSEEventType.DIMENSION_COMPLETE]:
            logger.info(f"[SSEManager] Session {session_id}: {event_type} sent to {len(subscribers)} subscribers")
        elif event_type == SSEEventType.RAG_RESULT:
            logger.info(f"[SSEManager] Session {session_id}: {event_type} sent to {len(subscribers)} subscribers")
        elif len(subscribers) > 0:
            logger.debug(f"[SSEManager] Session {session_id}: {event_type} sent to {len(subscribers)} subscribers")

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
    def cleanup_expired_sessions(cls, cutoff_time: datetime = None) -> Dict[str, int]:
        """
        Clean up expired sessions and orphan states.

        Args:
            cutoff_time: DateTime threshold for expiration (defaults to 24h ago)

        Returns:
            Dict with cleanup counts for each category
        """
        if cutoff_time is None:
            from datetime import timedelta
            cutoff_time = datetime.now() - timedelta(hours=24)

        cleaned = {
            "sessions": 0,
            "executions": 0,
            "streams": 0,
            "log_trackers": 0,
            "cache_cleans": 0,
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

        # Clean orphan caches via CACHE_CONFIG
        with cls._cache_lock:
            for event_type, (cache_attr, _) in cls.CACHE_CONFIG.items():
                cache_dict = getattr(cls, cache_attr, None)
                if cache_dict is None:
                    continue
                orphans = [sid for sid in cache_dict if sid not in current_session_ids]
                for sid in orphans:
                    del cache_dict[sid]
                cleaned["cache_cleans"] += len(orphans)

        # Clean orphan delta coalesce index
        orphan_delta_idx = [
            sid for sid in cls._delta_coalesce_index
            if sid not in current_session_ids
        ]
        for sid in orphan_delta_idx:
            del cls._delta_coalesce_index[sid]

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
            logger.info(f"[SSEManager] Cleanup completed: {cleaned}")

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

        # Clean up all critical event caches via CACHE_CONFIG
        for event_type in cls.CACHE_CONFIG:
            result_key = f"{event_type}_cache"
            result[result_key] = cls._clear_cache_for_session(session_id, event_type)

        # Clean up delta coalesce index
        cls._delta_coalesce_index.pop(session_id, None)

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