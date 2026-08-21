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
from sqlalchemy import Index, UniqueConstraint, ForeignKey

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

    # Session and dimension identification (cascade delete)
    session_id: str = Field(
        sa_column=Column(
            String,
            ForeignKey("planning_sessions.session_id", ondelete="CASCADE"),
            index=True,
        )
    )
    dimension_key: str = Field(index=True)
    layer: int = Field(index=True)

    # Version management
    version: int = Field(default=1, index=True)
    report_id: str = Field(unique=True, index=True)  # UUID for external reference

    # Content
    content: str = Field(sa_column=Text())
    summary: str = Field(sa_column=Text())  # Structured JSON summary
    instruction: Optional[str] = Field(
        default=None,
        sa_column=Column(Text)
    )  # instruction 列 = 结构化 JSON（observations/claims）

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


# ==========================================
# Uploaded File Models
# ==========================================

class UploadedFile(SQLModel, table=True):
    """
    Uploaded file storage table
    上传文件存储表

    Replaces disk-based file storage with database storage.
    Supports automatic cleanup via foreign key cascade.
    """
    __tablename__ = "uploaded_files"

    # Primary key (auto-increment)
    id: Optional[int] = Field(default=None, primary_key=True)

    # Session relationship with cascade delete
    session_id: str = Field(
        sa_column=Column(
            String,
            ForeignKey("planning_sessions.session_id", ondelete="CASCADE"),
            index=True,
        ),
    )

    # File classification
    file_category: str = Field(index=True)  # "village_data", "task_description", "constraint"
    file_type: str = Field(index=True)       # "document", "geojson", "shapefile", etc.

    # File metadata
    filename: str = Field(max_length=255)
    original_filename: str = Field(max_length=255)
    file_size: int                           # Size in bytes
    content_type: str = Field(max_length=100)  # MIME type

    # Parsed content
    parsed_text: Optional[str] = Field(
        default=None,
        sa_column=Text()  # For doc/docx/pdf/pptx parsed text
    )

    # GIS data (JSON column for GeoJSON FeatureCollection)
    gis_data: Optional[Dict[str, Any]] = Field(
        default=None,
        sa_column=Column(JSON)
    )

    # GIS data type inference (for geojson files)
    gis_data_type: Optional[str] = None  # "boundary", "water", "road", "residential", etc.

    # Processing status
    parse_status: str = Field(default="pending")  # "pending", "success", "failed"
    parse_error: Optional[str] = None

    # Timestamps
    created_at: datetime = Field(default_factory=datetime.now)

    # Table options
    __table_args__ = (
        Index("idx_uploaded_session_category", "session_id", "file_category"),
        Index("idx_uploaded_session_type", "session_id", "file_type"),
    )


# ==========================================
# Planning Bundle Models
# ==========================================

class PlanningBundle(SQLModel, table=True):
    """
    Planning bundle snapshot table
    规划数据包快照表

    Stores versioned session-level VillageBundle retrieval projections:
    spatial features, input references and evidence/report manifests. Long
    report bodies remain in their canonical source store and are not embedded
    into every snapshot.
    """
    __tablename__ = "planning_bundles"

    # Primary key (auto-increment)
    id: Optional[int] = Field(default=None, primary_key=True)

    # Session relationship with cascade delete
    session_id: str = Field(
        sa_column=Column(
            String,
            ForeignKey("planning_sessions.session_id", ondelete="CASCADE"),
            index=True,
        )
    )

    # Version management
    version: int = Field(default=1, index=True)

    # Content (full JSON snapshot of the session VillageBundle)
    bundle_json: str = Field(sa_column=Text())
    sha256: str = Field(default="")
    # CAS descriptor reference (JSON string) for the bundle blob in the CAS store
    bundle_ref: Optional[str] = None

    # Metadata
    trigger_reason: Optional[str] = None  # "layer1" | "layer2" | "layer3" | "final" | "manual"
    built_at: datetime = Field(default_factory=datetime.now)

    # Table options
    __table_args__ = (
        Index("idx_planning_bundle_session_version", "session_id", "version"),
    )


# ==========================================
# Step Report Models (P2: 每步 Report 落库)
# ==========================================

class StepReportModel(SQLModel, table=True):
    """
    Step report table — 全链步骤 Report（L1/L3/EXPLORE/PARSE/EXECUTE/KG_PREBUILD）。

    每条记录对应一个执行步骤的输入/输出/诊断，供 positioning-trace 面板
    按 session + stage + dimension_key 下钻定位。
    """
    __tablename__ = "step_reports"

    # Primary key (auto-increment)
    id: Optional[int] = Field(default=None, primary_key=True)

    # Session + stage identification (cascade delete)
    session_id: str = Field(
        sa_column=Column(
            String,
            ForeignKey("planning_sessions.session_id", ondelete="CASCADE"),
            index=True,
        )
    )
    stage: str = Field(index=True)          # KG_PREBUILD / L1 / L3 / EXPLORE / PARSE / EXECUTE
    step_name: str = Field(default="")      # "analyze_dimension:location"
    dimension_key: str = Field(default="", index=True)
    layer: int = Field(default=0, index=True)

    # Inputs / outputs / diagnostics (JSON)
    inputs: Optional[Dict[str, Any]] = Field(default=None, sa_column=Column(JSON))
    outputs: Optional[Dict[str, Any]] = Field(default=None, sa_column=Column(JSON))
    artifacts: Optional[List[Dict[str, Any]]] = Field(default=None, sa_column=Column(JSON))
    diagnostics: Optional[Dict[str, Any]] = Field(default=None, sa_column=Column(JSON))

    # Timestamp
    timestamp: datetime = Field(default_factory=datetime.now)

    # Table options
    __table_args__ = (
        Index("idx_step_session_stage", "session_id", "stage"),
        Index("idx_step_session_dim", "session_id", "dimension_key"),
    )


class RunEvent(SQLModel, table=True):
    """Append-only public run event log used by REST sync and SSE replay."""

    __tablename__ = "run_events"

    id: Optional[int] = Field(default=None, primary_key=True)
    session_id: str = Field(index=True)
    seq: int = Field(index=True)
    event_type: str = Field(index=True)
    payload: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=datetime.now)

    __table_args__ = (
        UniqueConstraint("session_id", "seq", name="uq_run_events_session_seq"),
        Index("idx_run_events_session_seq", "session_id", "seq"),
    )


__all__ = [
    "PlanningSession",
    "UISession",
    "DimensionReport",
    "UploadedFile",
    "PlanningBundle",
    "StepReportModel",
    "RunEvent",
]
