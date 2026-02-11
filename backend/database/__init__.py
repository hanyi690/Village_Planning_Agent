"""
Database module for Village Planning Agent
村庄规划智能体数据库模块

Provides SQLite + SQLModel persistence for planning sessions, checkpoints,
and UI conversations.
"""

from .engine import get_session, init_db
from .models import (
    PlanningSession,
    Checkpoint,
    UISession,
    UIMessage
)
from .operations import (
    # Planning session operations
    create_planning_session,
    get_planning_session,
    update_planning_session,
    delete_planning_session,
    list_planning_sessions,
    update_session_state,
    add_session_event,
    get_session_events,

    # Checkpoint operations
    create_checkpoint,
    get_checkpoint,
    list_checkpoints,
    delete_checkpoint,

    # UI session operations
    create_ui_session,
    get_ui_session,
    update_ui_session,
    delete_ui_session,
    list_ui_sessions,

    # UI message operations
    create_ui_message,
    get_ui_messages,
    delete_ui_messages,
)

__all__ = [
    # Engine
    "get_session",
    "init_db",

    # Models
    "PlanningSession",
    "Checkpoint",
    "UISession",
    "UIMessage",

    # Operations
    "create_planning_session",
    "get_planning_session",
    "update_planning_session",
    "delete_planning_session",
    "list_planning_sessions",
    "update_session_state",
    "add_session_event",
    "get_session_events",

    "create_checkpoint",
    "get_checkpoint",
    "list_checkpoints",
    "delete_checkpoint",

    "create_ui_session",
    "get_ui_session",
    "update_ui_session",
    "delete_ui_session",
    "list_ui_sessions",

    "create_ui_message",
    "get_ui_messages",
    "delete_ui_messages",
]
