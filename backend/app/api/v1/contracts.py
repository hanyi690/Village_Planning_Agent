"""Strict public contracts for the stable frontend API."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class PublicModel(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


DeliveryStatus = Literal['complete', 'partial', 'diagnostic_only']
SessionRunStatus = Literal[
    'pending', 'running', 'paused', 'reviewing', 'revising', 'completed', 'failed'
]


class ResourceLinks(PublicModel):
    events: str
    event_sync: str
    delivery: str
    map_layers: str
    human_review: str


class SessionProjection(PublicModel):
    schema_version: Literal['1.0'] = '1.0'
    session_id: str
    status: SessionRunStatus
    active_stage: str = ''
    phase: str = ''
    progress: float = Field(default=0.0, ge=0.0, le=100.0)
    human_review_pending: bool = False
    delivery_status: DeliveryStatus | None = None
    statutory_complete: bool = False
    last_event_seq: int = Field(default=0, ge=0)
    links: ResourceLinks


class SessionCreated(PublicModel):
    session_id: str
    stream_url: str
    status: Literal['running'] = 'running'


class DeliveryProjection(PublicModel):
    schema_version: Literal['1.0'] = '1.0'
    session_id: str
    available: bool
    delivery_status: DeliveryStatus | None = None
    statutory_complete: bool = False
    snapshot_checksum: str = ''
    deferral_summary: dict[str, Any] = Field(default_factory=dict)
    diagnostic_summary: dict[str, Any] = Field(default_factory=dict)
    deliverables: list[dict[str, Any]] = Field(default_factory=list)
    downloads: list[str] = Field(default_factory=list)


class MapLayer(PublicModel):
    layer_type: Literal['current', 'planned', 'overlay', 'constraint']
    layer_name: str
    crs: str = ''
    checksum: str = ''
    feature_count: int = Field(default=0, ge=0)
    geojson: dict[str, Any]


class MapLayerCollection(PublicModel):
    schema_version: Literal['1.0'] = '1.0'
    session_id: str
    snapshot_checksum: str = ''
    delivery_status: DeliveryStatus | None = None
    layers: list[MapLayer] = Field(default_factory=list)


class HumanReviewProjection(PublicModel):
    schema_version: Literal['1.0'] = '1.0'
    session_id: str
    pending: bool
    event_id: str | None = None
    paused_stage: str = ''
    items: list[dict[str, Any]] = Field(default_factory=list)


class HumanReviewDecision(PublicModel):
    event_id: str
    action: Literal['retry', 'approve', 'reject']
    decisions: dict[str, Any] = Field(default_factory=dict)


class ApiError(PublicModel):
    schema_version: Literal['1.0'] = '1.0'
    code: str
    message: str
    request_id: str
    retryable: bool = False
    details: dict[str, Any] = Field(default_factory=dict)


class EventBase(PublicModel):
    schema_version: Literal['1.0'] = '1.0'
    event_id: str
    seq: int = Field(ge=1)
    session_id: str
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ProgressEvent(EventBase):
    type: Literal['progress'] = 'progress'
    data: dict[str, Any] = Field(default_factory=dict)


class HumanReviewEvent(EventBase):
    type: Literal['human_review'] = 'human_review'
    data: HumanReviewProjection


class DeliveryReadyEvent(EventBase):
    type: Literal['delivery_ready'] = 'delivery_ready'
    data: DeliveryProjection


class CompletedEvent(EventBase):
    type: Literal['completed'] = 'completed'
    data: dict[str, Any] = Field(default_factory=dict)


class FailedEvent(EventBase):
    type: Literal['failed'] = 'failed'
    data: ApiError


class ResyncRequiredEvent(EventBase):
    type: Literal['resync_required'] = 'resync_required'
    data: dict[str, Any] = Field(default_factory=dict)


PublicEvent = Annotated[
    ProgressEvent
    | HumanReviewEvent
    | DeliveryReadyEvent
    | CompletedEvent
    | FailedEvent
    | ResyncRequiredEvent,
    Field(discriminator='type'),
]


class EventSyncResponse(PublicModel):
    schema_version: Literal['1.0'] = '1.0'
    session_id: str
    events: list[dict[str, Any]] = Field(default_factory=list)
    last_seq: int = Field(default=0, ge=0)
    resync_required: bool = False


__all__ = [
    'ApiError', 'DeliveryProjection', 'EventSyncResponse', 'HumanReviewDecision',
    'HumanReviewProjection', 'MapLayer', 'MapLayerCollection', 'PublicEvent',
    'ResourceLinks', 'SessionCreated', 'SessionProjection',
]
