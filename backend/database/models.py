"""
SQLModel database models
SQLModel 数据库模型

Defines all database tables for planning sessions, checkpoints,
and UI conversations.

简化版：移除冗余状态字段，状态由 LangGraph Checkpoint 统一管理。
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

    状态数据由 LangGraph AsyncSqliteSaver 自动存储在 checkpoints 表中。
    移除冗余字段：status, is_executing, stream_state
    """
    __tablename__ = "planning_sessions"

    # Primary key
    session_id: str = Field(primary_key=True)

    # Basic info
    project_name: str = Field(index=True)

    # User input
    village_data: Optional[str] = Field(
        default=None,
        sa_column=Text()
    )
    task_description: str = Field(default=DEFAULT_TASK_DESCRIPTION)
    constraints: str = Field(default=DEFAULT_CONSTRAINTS)

    # Output
    output_path: Optional[str] = None

    # Error info (业务元数据)
    execution_error: Optional[str] = Field(
        default=None,
        sa_column=Text()
    )

    # Timestamps
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None

    # Table options for composite indexes
    __table_args__ = (
        Index("idx_project_created", "project_name", "created_at"),
    )


# ==========================================
# Note: Checkpoint table is managed by LangGraph's AsyncSqliteSaver
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

    支持 Upsert：使用 (session_id, message_id) 作为唯一标识
    """
    __tablename__ = "ui_messages"

    # Primary key (auto-increment)
    id: Optional[int] = Field(default=None, primary_key=True)

    # Foreign key
    session_id: str = Field(foreign_key="ui_sessions.conversation_id", index=True)

    # 前端消息 ID（唯一标识，用于 upsert）
    message_id: str = Field(index=True)

    # Message content
    role: str = Field(index=True)  # user/assistant/system
    content: str = Field(sa_column=Text())
    message_type: str = Field(default="text")  # text/file/progress/action/result/error/system

    # Message metadata (JSON)
    message_metadata: Optional[Dict[str, Any]] = Field(
        default=None,
        sa_column=Column(JSON)
    )

    # Timestamps
    created_at: datetime = Field(default_factory=datetime.now)
    timestamp: datetime = Field(default_factory=datetime.now)

    # Relationships
    session: UISession = Relationship(back_populates="messages")

    # 唯一约束：(session_id, message_id) 必须唯一
    __table_args__ = (
        UniqueConstraint("session_id", "message_id", name="uq_session_message"),
    )


# ==========================================
# Dimension Revision Models
# ==========================================

class DimensionRevision(SQLModel, table=True):
    """
    Dimension revision table
    维度修订表

    Stores revision history for each dimension.

    SSOT: Checkpoint 仍是维度当前内容的唯一真实源
    此表仅作为历史日志，不影响当前状态
    """
    __tablename__ = "dimension_revisions"

    # Primary key (auto-increment)
    id: Optional[int] = Field(default=None, primary_key=True)

    # Session and dimension identification
    session_id: str = Field(foreign_key="ui_sessions.conversation_id", index=True)
    layer: int = Field(index=True)  # 层级 (1/2/3)
    dimension_key: str = Field(index=True)  # 维度标识

    # Content
    content: str = Field(sa_column=Text())
    previous_content: Optional[str] = Field(
        default=None,
        sa_column=Text()
    )
    previous_content_hash: Optional[str] = None

    # Metadata
    reason: Optional[str] = None
    created_by: Optional[str] = None
    version: int = Field(default=1, index=True)

    # Timestamp
    created_at: datetime = Field(default_factory=datetime.now)

    # Table options for composite indexes
    __table_args__ = (
        Index("idx_revision_session_dim", "session_id", "dimension_key"),
        Index("idx_revision_session_version", "session_id", "layer", "dimension_key", "version"),
    )


__all__ = [
    "PlanningSession",
    "UISession",
    "UIMessage",
    "DimensionRevision",
]
