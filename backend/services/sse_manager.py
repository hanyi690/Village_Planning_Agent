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
from threading import Lock
from typing import Any, Dict, List, Optional, Set

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
    # Critical Event Cache (prevent event loss when no subscribers)
    # ============================================

    # Cache dimension_complete events: session_id -> dimension_key -> event
    _last_dimension_complete: Dict[str, Dict[str, Dict[str, Any]]] = {}

    # Cache layer_completed events: session_id -> layer -> event
    _last_layer_completed: Dict[str, Dict[int, Dict[str, Any]]] = {}

    # Locks for critical event cache
    _dimension_cache_lock = Lock()
    _layer_cache_lock = Lock()

    @classmethod
    def save_event_loop(cls, loop: asyncio.AbstractEventLoop) -> None:
        """
        Save the main event loop reference for cross-thread publishing.

        Should be called during application startup.
        """
        cls._main_event_loop = loop
        logger.info("[SSEManager] Main event loop saved, cross-thread publishing enabled")

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
        queue = asyncio.Queue(maxsize=500)

        with cls._subscribers_lock:
            if session_id not in cls._session_subscribers:
                cls._session_subscribers[session_id] = set()
            cls._session_subscribers[session_id].add(queue)

        # Sync historical events
        historical_count = 0
        with cls._sessions_lock:
            if session_id in cls._sessions:
                events = cls._sessions[session_id].get("events", [])
                for event in events:
                    try:
                        queue.put_nowait(event)
                        historical_count += 1
                    except asyncio.QueueFull:
                        logger.warning(f"[SSEManager] Session {session_id}: Queue full, dropping event")
                        break

        # Sync cached dimension_complete events
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

        # Sync cached layer_completed events
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

        total_synced = historical_count + cached_dim_count + cached_layer_count
        logger.info(
            f"[SSEManager] Session {session_id}: Subscribed, "
            f"historical={historical_count}, cached_dim={cached_dim_count}, cached_layer={cached_layer_count}, total={total_synced}"
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

        # Cache critical events regardless of subscriber status
        if event_type == "dimension_complete":
            dimension_key = event.get("dimension_key", "")
            if dimension_key:
                with cls._dimension_cache_lock:
                    if session_id not in cls._last_dimension_complete:
                        cls._last_dimension_complete[session_id] = {}
                    cls._last_dimension_complete[session_id][dimension_key] = event
                    logger.info(f"[SSEManager] Cached dimension_complete for {session_id}/{dimension_key}")

        elif event_type == "layer_completed":
            layer = event.get("layer", 0)
            if layer:
                with cls._layer_cache_lock:
                    if session_id not in cls._last_layer_completed:
                        cls._last_layer_completed[session_id] = {}
                    cls._last_layer_completed[session_id][layer] = event
                    logger.info(f"[SSEManager] Cached layer_completed for {session_id}/Layer{layer}")

        # If no subscribers, skip sending (events are already cached above)
        if not subscribers:
            if event_type in ["layer_completed", "dimension_complete"]:
                logger.warning(f"[SSEManager] Session {session_id}: No subscribers, event cached")
            return

        success_count = 0
        for queue in list(subscribers):
            try:
                queue.put_nowait(event)
                success_count += 1
            except asyncio.QueueFull:
                logger.warning(f"[SSEManager] Session {session_id}: Queue full, event dropped")

        if event_type in ["layer_completed", "dimension_complete"]:
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
            "layer_caches": 0,
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

        # Clean orphan layer_completed caches
        with cls._layer_cache_lock:
            orphan_layer_caches = [
                sid for sid in cls._last_layer_completed
                if sid not in current_session_ids
            ]
            for sid in orphan_layer_caches:
                del cls._last_layer_completed[sid]
                cleaned["layer_caches"] += 1

        total = sum(cleaned.values())
        if total > 0:
            logger.info(
                f"[SSEManager] Cleanup completed: "
                f"sessions={cleaned['sessions']}, executions={cleaned['executions']}, "
                f"streams={cleaned['streams']}, trackers={cleaned['log_trackers']}, "
                f"dim_caches={cleaned['dimension_caches']}, layer_caches={cleaned['layer_caches']}"
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

        with cls._layer_cache_lock:
            if session_id in cls._last_layer_completed:
                del cls._last_layer_completed[session_id]
                result["layer_cache"] = True
            else:
                result["layer_cache"] = False

        logger.debug(f"[SSEManager] Session {session_id}: all states deleted")
        return result


# Singleton instance for easy import
sse_manager = SSEManager()


__all__ = ["SSEManager", "sse_manager"]