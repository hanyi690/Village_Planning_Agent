"""
SQLModel database models
SQLModel 数据库模型

Defines all database tables for planning sessions, checkpoints,
and UI conversations.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlmodel import (
    SQLModel,
    Field,
    Relationship,
    Column,
    JSON,
    String,
    Text,
    Boolean,
    Integer,
    DateTime
)
from sqlalchemy import Index, UniqueConstraint

from src.core.config import (
    DEFAULT_TASK_DESCRIPTION,
    DEFAULT_CONSTRAINTS,
)


# ==========================================
# Planning Session Models
# ==========================================

class PlanningSession(SQLModel, table=True):
    """
    Planning session table
    规划会话表（精简版 - 只存储业务元数据）
    
    状态数据由 AsyncSqliteSaver 自动存储在 checkpoints 表中。
    """
    __tablename__ = "planning_sessions"

    # Primary key
    session_id: str = Field(primary_key=True)

    # Basic info
    project_name: str = Field(index=True)
    status: str = Field(index=True)  # running/paused/completed/failed
    execution_error: Optional[str] = Field(
        default=None,
        sa_column=Text()  # 执行错误信息(业务元数据)
    )

    # 【新增】执行状态 - 替代内存中的 _active_executions
    is_executing: bool = Field(default=False, index=True)

    # 【新增】流状态 - 替代内存中的 _stream_states
    # 值: "active", "paused", "completed"
    stream_state: str = Field(default="active", index=True)

    # User input
    village_data: Optional[str] = Field(
        default=None,
        sa_column=Text()       # 可空列
    )
    task_description: str = Field(default=DEFAULT_TASK_DESCRIPTION)
    constraints: str = Field(default=DEFAULT_CONSTRAINTS)

    # ✅ 精简：删除手动维护的状态字段
    # 以下字段现在由 AsyncSqliteSaver 在 checkpoints 表中自动管理：
    # - current_layer, layer_X_completed
    # - pause_after_step, waiting_for_review
    # - state_snapshot, execution_complete, execution_error
    # - events, sent_layer_events, sent_pause_events

    # Output
    output_path: Optional[str] = None

    # Timestamps
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None

    # Table options for composite indexes
    __table_args__ = (
        Index("idx_status_created", "status", "created_at"),
        Index("idx_project_status", "project_name", "status"),
    )


# ==========================================
# Note: Checkpoint table is now managed by LangGraph's AsyncSqliteSaver
# The old Checkpoint model has been removed to avoid schema conflicts
# ==========================================

# ==========================================
# UI Session Models
# ==========================================

class UISession(SQLModel, table=True):
    """
    UI session table
    UI 会话表

    Stores UI conversation sessions.
    """
    __tablename__ = "ui_sessions"

    # Primary key
    conversation_id: str = Field(primary_key=True)

    # Session info
    status: str = Field(default="idle", index=True)
    project_name: Optional[str] = None
    task_id: Optional[str] = Field(index=True)  # Links to planning session

    # Timestamps
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    # Relationships
    messages: List["UIMessage"] = Relationship(back_populates="session")


class UIMessage(SQLModel, table=True):
    """
    UI message table
    UI 消息表

    Stores messages in UI conversations.
    
    ✅ 支持 Upsert：使用 (session_id, message_id) 作为唯一标识
    """
    __tablename__ = "ui_messages"

    # Primary key (auto-increment)
    id: Optional[int] = Field(default=None, primary_key=True)

    # Foreign key
    session_id: str = Field(foreign_key="ui_sessions.conversation_id", index=True)

    # ✅ 前端消息 ID（唯一标识，用于 upsert）
    message_id: str = Field(index=True)  # 前端生成的唯一 ID，如 "msg-1234567890-1" 或 "layer_report_1"

    # Message content
    role: str = Field(index=True)  # user/assistant/system
    content: str = Field(sa_column=Text())
    message_type: str = Field(default="text")  # text/file/progress/action/result/error/system

    # Message metadata (JSON) - additional message information
    message_metadata: Optional[Dict[str, Any]] = Field(
        default=None,
        sa_column=Column(JSON)
    )

    # Timestamp
    timestamp: datetime = Field(default_factory=datetime.now)

    # Relationships
    session: UISession = Relationship(back_populates="messages")

    # ✅ 唯一约束：(session_id, message_id) 必须唯一
    __table_args__ = (
        UniqueConstraint("session_id", "message_id", name="uq_session_message"),
    )


# ==========================================
# Indices
# ==========================================

# Create composite indices for common queries
# These are created automatically by SQLModel based on index=True in field definitions


__all__ = [
    "PlanningSession",
    "Checkpoint",
    "UISession",
    "UIMessage",
]
