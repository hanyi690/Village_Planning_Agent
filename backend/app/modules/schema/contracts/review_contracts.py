from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class ReviewStatus(str, Enum):
    AWAITING_REVIEW = "awaiting_review"
    APPROVED = "approved"
    CHANGES_REQUESTED = "changes_requested"


class ArtifactDescriptorProjection(BaseModel):
    """Lightweight immutable descriptor copied into a review projection."""

    digest: str
    descriptor_digest: str
    media_type: str = "application/json"
    size_bytes: int = 0
    schema_id: str
    schema_version: str
    semantic_digest: str
    parent_digests: dict[str, str] = Field(default_factory=dict)
    producer_stage: str
    run_id: str
    branch_id: str
    provenance: dict[str, Any] = Field(default_factory=dict)


class ReviewPackage(BaseModel):
    review_id: str = ""
    revision: int = 1
    run_id: str
    module: str
    summary_md: str = ""
    artifact_ref: ArtifactDescriptorProjection | None = None
    trace_json: dict[str, Any] = Field(default_factory=dict)
    preview_geojson: dict[str, Any] | None = None
    before_after_geojson: dict[str, Any] | None = None
    status: ReviewStatus = ReviewStatus.AWAITING_REVIEW
    decision: "ReviewDecision | None" = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class HumanReviewRequest(BaseModel):
    request_id: str
    stage: str = ""
    reason: str = ""
    options: list[dict] = Field(default_factory=list)
    context_refs: list[str] = Field(default_factory=list)


class ReviewDecision(BaseModel):
    request_id: str
    decision: str = ""  # "approved" | "rejected" | "changes_requested"
    comments: str = ""
    decided_by: str = ""
    decided_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class ReviewComment(BaseModel):
    comment_id: str
    author: str = ""
    body: str = ""
    target_artifact: str = ""
    target_line: int | None = None
