from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


class StageStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    BLOCKED = "blocked"
    AWAITING_REVIEW = "awaiting_review"


class StageIssue(BaseModel):
    stage: str
    severity: str  # "info" | "warning" | "error"
    code: str
    message: str
    detail: str | None = None
    related_artifact_id: str | None = None


class ContractMeta(BaseModel):
    schema_version: str = "1.0"
    context_version: str
    artifact_id: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
