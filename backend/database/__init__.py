"""
Database module for Village Planning Agent
村庄规划智能体数据库模块

Provides SQLite + SQLModel persistence for planning sessions, checkpoints,
and UI conversations with pure async support.
"""

from .engine import (
    # Sync engine functions (deprecated, kept for backward compatibility)
    get_session,
    init_db,
    # Async engine functions (recommended)
    get_async_session,
    init_async_db,
    get_async_engine,
    dispose_async_engine,
    get_db_path,
)
from .models import (
    PlanningSession,
    Checkpoint,
    UISession,
    UIMessage
)
from .operations_async import (
    # Async planning session operations (recommended)
    create_planning_session_async,
    get_planning_session_async,
    update_planning_session_async,
    delete_planning_session_async,
    list_planning_sessions_async,
    update_session_state_async,
    add_session_event_async,
    get_session_events_async,
    # Async checkpoint operations (recommended)
    create_checkpoint_async,
    get_checkpoint_async,
    list_checkpoints_async,
    delete_checkpoint_async,
    # Async UI session operations (recommended)
    create_ui_session_async,
    get_ui_session_async,
    update_ui_session_async,
    delete_ui_session_async,
    list_ui_sessions_async,
    # Async UI message operations (recommended)
    create_ui_message_async,
    get_ui_messages_async,
    delete_ui_messages_async,
)

__all__ = [
    # Engine (sync - deprecated)
    "get_session",
    "init_db",
    # Engine (async - recommended)
    "get_async_session",
    "init_async_db",
    "get_async_engine",
    "dispose_async_engine",
    "get_db_path",

    # Models
    "PlanningSession",
    "Checkpoint",
    "UISession",
    "UIMessage",

    # Async operations (recommended)
    "create_planning_session_async",
    "get_planning_session_async",
    "update_planning_session_async",
    "delete_planning_session_async",
    "list_planning_sessions_async",
    "update_session_state_async",
    "add_session_event_async",
    "get_session_events_async",
    "create_checkpoint_async",
    "get_checkpoint_async",
    "list_checkpoints_async",
    "delete_checkpoint_async",
    "create_ui_session_async",
    "get_ui_session_async",
    "update_ui_session_async",
    "delete_ui_session_async",
    "list_ui_sessions_async",
    "create_ui_message_async",
    "get_ui_messages_async",
    "delete_ui_messages_async",
]