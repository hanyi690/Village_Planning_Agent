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


# ==========================================
# Planning Session Models
# ==========================================

class PlanningSession(SQLModel, table=True):
    """
    Planning session table
    规划会话表

    Stores complete state for village planning sessions.
    """
    __tablename__ = "planning_sessions"

    # Primary key
    session_id: str = Field(primary_key=True)

    # Basic info
    project_name: str = Field(index=True)
    status: str = Field(index=True)  # running/paused/completed/failed

    # User input
    village_data: Optional[str] = Field(
        default=None, 
        sa_column=Text()       # ✅ 改为 Optional + default=None，生成可空列
    )
    task_description: str = Field(default="制定村庄总体规划方案")
    constraints: str = Field(default="无特殊约束")

    # Flow control
    current_layer: int = Field(default=1)
    previous_layer: int = Field(default=1)
    layer_1_completed: bool = Field(default=False)
    layer_2_completed: bool = Field(default=False)
    layer_3_completed: bool = Field(default=False)

    # Review settings
    need_human_review: bool = Field(default=False)
    human_feedback: Optional[str] = None
    need_revision: bool = Field(default=False)

    # Step mode
    step_mode: bool = Field(default=False)
    pause_after_step: bool = Field(default=False)

    # Output
    output_path: Optional[str] = None

    # Complete state snapshot (JSON) - for checkpoint restoration
    state_snapshot: Optional[Dict[str, Any]] = Field(
        default=None,
        sa_column=Column(JSON)
    )

    # Request parameters (JSON) - for session reconstruction
    request_params: Optional[Dict[str, Any]] = Field(
        default=None,
        sa_column=Column(JSON)
    )

    # Event tracking
    events: List[Dict[str, Any]] = Field(
        default_factory=list,          # ⭐ 修改点：自动初始化为 []
        sa_column=Column(JSON)
    )

    sent_layer_events: List[str] = Field(
        default_factory=list,          # JSON 数组存储已发送的 layer_completed 事件标识
        sa_column=Column(JSON)
    )

    sent_pause_events: List[str] = Field(
        default_factory=list,          # 存储 pause_layer_X 事件标识
        sa_column=Column(JSON)
    )
    
    # Execution tracking
    execution_complete: bool = Field(default=False)
    execution_error: Optional[str] = None

    # Timestamps
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None

    # Relationships
    checkpoints: List["Checkpoint"] = Relationship(back_populates="session")

    # Table options for composite indexes
    __table_args__ = (
        Index("idx_status_created", "status", "created_at"),
        Index("idx_project_status", "project_name", "status"),
    )


class Checkpoint(SQLModel, table=True):
    """
    Checkpoint table
    检查点表

    Stores layer completion checkpoints for rollback support.
    """
    __tablename__ = "checkpoints"

    # Primary key
    checkpoint_id: str = Field(primary_key=True)

    # Foreign key
    session_id: str = Field(foreign_key="planning_sessions.session_id", index=True)

    # Layer info
    layer: int = Field(index=True)
    description: str = Field(default="")

    # State snapshot (JSON) - complete state for this checkpoint
    state_snapshot: Dict[str, Any] = Field(
        default={},
        sa_column=Column(JSON)
    )

    # Checkpoint metadata (JSON) - additional checkpoint information
    checkpoint_metadata: Optional[Dict[str, Any]] = Field(
        default=None,
        sa_column=Column(JSON)
    )

    # Timestamp
    timestamp: datetime = Field(default_factory=datetime.now)

    # Relationships
    session: PlanningSession = Relationship(back_populates="checkpoints")


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
    """
    __tablename__ = "ui_messages"

    # Primary key (auto-increment)
    id: Optional[int] = Field(default=None, primary_key=True)

    # Foreign key
    session_id: str = Field(foreign_key="ui_sessions.conversation_id", index=True)

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
