"""Application-owned view models consumed by API transport."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class TaskStatus(str, Enum):
    """任务状态枚举"""
    pending = "pending"
    running = "running"
    paused = "paused"
    reviewing = "reviewing"
    revising = "revising"
    completed = "completed"
    failed = "failed"


class ProjectionModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SessionView(ProjectionModel):
    session_id: str
    status: str
    active_stage: str = ""
    phase: str = ""
    progress: float = Field(default=0.0, ge=0.0, le=100.0)
    human_review_pending: bool = False
    delivery_status: str | None = None
    statutory_complete: bool = False
    last_event_seq: int = Field(default=0, ge=0)
    links: dict[str, str]


class DeliveryView(ProjectionModel):
    session_id: str
    available: bool
    delivery_status: str | None = None
    statutory_complete: bool = False
    snapshot_checksum: str = ""
    deferral_summary: dict[str, object] = Field(default_factory=dict)
    diagnostic_summary: dict[str, object] = Field(default_factory=dict)
    deliverables: list[dict[str, object]] = Field(default_factory=list)
    downloads: list[str] = Field(default_factory=list)


class MapLayerView(ProjectionModel):
    layer_type: str
    layer_name: str
    crs: str = ""
    checksum: str = ""
    feature_count: int = Field(default=0, ge=0)
    geojson: dict[str, object]


class MapLayerCollectionView(ProjectionModel):
    session_id: str
    snapshot_checksum: str = ""
    delivery_status: str | None = None
    layers: list[MapLayerView] = Field(default_factory=list)


class HumanReviewView(ProjectionModel):
    session_id: str
    pending: bool
    event_id: str | None = None
    paused_stage: str = ""
    items: list[dict[str, object]] = Field(default_factory=list)


__all__ = [
    "DeliveryView",
    "HumanReviewView",
    "MapLayerCollectionView",
    "MapLayerView",
    "SessionView",
    "TaskStatus",
]
