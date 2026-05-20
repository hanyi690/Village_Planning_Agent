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

from app.core.settings import (
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
    village_name: str = Field(default="", index=True)

    # 行政区划信息
    province: str = Field(default="")      # 省份
    city: str = Field(default="")          # 地级市
    county: str = Field(default="")        # 县/区
    township: str = Field(default="")      # 乡镇
    planning_period: str = Field(default="2022-2035年")  # 规划期限

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


# ==========================================
# Dimension Report Models
# ==========================================

class DimensionReport(SQLModel, table=True):
    """
    Dimension report table
    维度报告表

    替代文件存储，统一使用数据库存储报告内容。
    支持版本历史、知识来源追踪。
    """
    __tablename__ = "dimension_reports"

    # Primary key (auto-increment)
    id: Optional[int] = Field(default=None, primary_key=True)

    # Session and dimension identification
    session_id: str = Field(foreign_key="planning_sessions.session_id", index=True)
    dimension_key: str = Field(index=True)
    layer: int = Field(index=True)

    # Version management
    version: int = Field(default=1, index=True)
    report_id: str = Field(unique=True, index=True)  # UUID for external reference

    # Content
    content: str = Field(sa_column=Text())
    summary: str = Field(sa_column=Text())  # Structured JSON summary

    # Metadata
    revision_trigger: Optional[str] = None

    # Knowledge sources (RAG references)
    knowledge_sources: Optional[List[Dict[str, Any]]] = Field(
        default=None,
        sa_column=Column(JSON)
    )

    # GIS data references
    gis_data: Optional[List[Dict[str, Any]]] = Field(
        default=None,
        sa_column=Column(JSON)
    )

    # Timestamps
    generated_at: datetime = Field(default_factory=datetime.now)

    # Table options
    __table_args__ = (
        Index("idx_report_session_dim", "session_id", "dimension_key"),
        Index("idx_report_session_version", "session_id", "dimension_key", "version"),
    )


__all__ = [
    "PlanningSession",
    "UISession",
    "UIMessage",
    "DimensionRevision",
    "DimensionReport",
]
