"""
Database module for Village Planning Agent
村庄规划智能体数据库模块

Provides SQLite + SQLModel persistence for planning sessions, checkpoints,
and UI conversations with pure async support.
"""

from .engine import (
    # Async engine functions
    get_async_session,
    init_async_db,
    get_async_engine,
    dispose_async_engine,
    get_db_path,
)
from .models import (
    PlanningSession,
    UISession,
    UIMessage
)
from .operations_async import (
    # Async planning session operations
    create_planning_session_async,
    get_planning_session_async,
    update_planning_session_async,
    delete_planning_session_async,
    list_planning_sessions_async,
    update_session_state_async,
    add_session_event_async,
    get_session_events_async,
    # Async UI session operations
    create_ui_session_async,
    get_ui_session_async,
    update_ui_session_async,
    delete_ui_session_async,
    list_ui_sessions_async,
    # Async UI message operations
    create_ui_message_async,
    get_ui_messages_async,
    delete_ui_messages_async,
)

__all__ = [
    # Engine (async)
    "get_async_session",
    "init_async_db",
    "get_async_engine",
    "dispose_async_engine",
    "get_db_path",

    # Models
    "PlanningSession",
    "UISession",
    "UIMessage",

    # Async operations
    "create_planning_session_async",
    "get_planning_session_async",
    "update_planning_session_async",
    "delete_planning_session_async",
    "list_planning_sessions_async",
    "update_session_state_async",
    "add_session_event_async",
    "get_session_events_async",
    "create_ui_session_async",
    "get_ui_session_async",
    "update_ui_session_async",
    "delete_ui_session_async",
    "list_ui_sessions_async",
    "create_ui_message_async",
    "get_ui_messages_async",
    "delete_ui_messages_async",
]
