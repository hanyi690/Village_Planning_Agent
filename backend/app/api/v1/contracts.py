"""Strict public contracts for the stable frontend API."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.contracts.evidence.evidence_contracts import (
    EvidenceBundle,
    SpatialCognitionEvidence,
)
from app.contracts.evidence.evidence_packet_contracts import EvidencePacket


class PublicModel(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


DeliveryStatus = Literal['complete', 'partial', 'diagnostic_only', 'no_planning_output']
SessionRunStatus = Literal[
    'pending', 'running', 'paused', 'reviewing', 'revising', 'completed', 'failed'
]


class ResourceLinks(PublicModel):
    events: str
    event_sync: str
    delivery: str
    map_layers: str
    human_review: str
    resume: str


class SessionProjection(PublicModel):
    schema_version: Literal['1.0'] = '1.0'
    session_id: str
    project_name: str = ''
    village_name: str = ''
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


class HistorySession(PublicModel):
    """Minimal persisted-session metadata exposed to the history sidebar."""

    session_id: str
    timestamp: str
    checkpoint_count: int = Field(default=0, ge=0)
    has_final_report: bool = False


class HistoryProject(PublicModel):
    """A project grouped with its persisted planning sessions."""

    name: str
    display_name: str
    session_count: int = Field(default=0, ge=0)
    sessions: list[HistorySession] = Field(default_factory=list)


class HistoryProjectList(PublicModel):
    """Stable response for the restart-safe planning history list."""

    schema_version: Literal['1.0'] = '1.0'
    projects: list[HistoryProject] = Field(default_factory=list)


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


class CurrentSourceLayer(PublicModel):
    """A configured, authoritative current-state vector source."""

    source_name: str
    source_layer_type: str
    layer_type: str
    layer_name: str
    display_role: str
    data_authority: Literal['authoritative_current'] = 'authoritative_current'
    requirement: Literal['baseline', 'mandatory', 'conditional', 'reference'] = 'baseline'
    crs: str = 'EPSG:4326'
    feature_count: int = Field(default=0, ge=0)
    geojson: dict[str, Any]
    metadata: dict[str, Any] = Field(default_factory=dict)


class CurrentSourceRaster(PublicModel):
    """Safe public manifest for a configured raster source.

    The local filesystem path is intentionally not exposed. Consumers use the
    manifest to explain availability while terrain analysis reads the raster
    through the backend catalog.
    """

    source_name: str
    layer_name: str
    layer_type: str = 'raster'
    format: str = ''
    crs: str = ''
    available: bool = False
    resolution: float | None = None
    width: int | None = None
    height: int | None = None
    bands: int | None = None
    dtype: str = ''
    bounds: dict[str, float] = Field(default_factory=dict)
    source_ref: str = ''
    reason: str = ''


class CurrentSourceLayerCollection(PublicModel):
    """Catalog-backed current GIS context, separate from DELIVER output."""

    schema_version: Literal['1.0'] = '1.0'
    village_name: str
    source: Literal['data_catalog'] = 'data_catalog'
    center: list[float] | None = None
    layers: list[CurrentSourceLayer] = Field(default_factory=list)
    rasters: list[CurrentSourceRaster] = Field(default_factory=list)
    diagnostics: list[str] = Field(default_factory=list)


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


class ResumeRequest(PublicModel):
    """Explicit cursor command for active interrupts or checkpoint forks."""

    mode: Literal['interrupt', 'checkpoint']
    event_id: str | None = None
    action: Literal['retry', 'approve', 'reject'] | None = None
    feedback: str = ''
    checkpoint_id: str | None = None
    replay_from_stage: str | None = None


class ResumeAccepted(PublicModel):
    schema_version: Literal['1.0'] = '1.0'
    session_id: str
    mode: Literal['interrupt', 'checkpoint']
    status: Literal['resumed', 'accepted']
    checkpoint_id: str = ''
    branch_id: str = ''
    resume_plan: dict[str, Any] = Field(default_factory=dict)


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


class EvidenceQueryRequest(PublicModel):
    """Frontend-safe request for the unified KG/bundle/L1 evidence path."""

    query: str = Field(min_length=1)
    village_name: str = ""
    request_type: Literal["spatial_lookup", "fact_check", "evidence_gap"] = "spatial_lookup"
    stage: str = "GROUND"
    dimension_key: str = ""
    query_purpose: str = "fact_check"
    context_refs: list[str] = Field(default_factory=list)
    questions: list[str] = Field(default_factory=list)
    required_facts: list[str] = Field(default_factory=list)
    entity_scope: list[str] = Field(default_factory=list)
    candidate_offset: int = Field(default=0, ge=0)
    candidate_limit: int = Field(default=12, ge=1, le=64)
    include_external: bool = False
    external_categories: list[str] = Field(default_factory=list, max_length=8)


class EvidenceQueryResponse(PublicModel):
    """Bounded answer that can be rendered by the map and planning UI."""

    schema_version: Literal["1.0"] = "1.0"
    session_id: str
    request: str
    evidence_bundle: EvidenceBundle
    spatial_cognition: SpatialCognitionEvidence | None = None
    evidence_packet: EvidencePacket | None = None


__all__ = [
    'ApiError', 'DeliveryProjection', 'EventSyncResponse', 'HumanReviewDecision',
    'HumanReviewProjection', 'MapLayer', 'MapLayerCollection', 'PublicEvent',
    'ResourceLinks', 'ResumeAccepted', 'ResumeRequest', 'SessionCreated', 'SessionProjection',
    'EvidenceQueryRequest', 'EvidenceQueryResponse',
]
