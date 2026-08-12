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
    """Base for authoritative root artifacts (stage outputs).

    Only ROOT artifacts inherit this — leaf value objects (nested in a root)
    are plain BaseModel and do NOT carry schema/context/artifact metadata.
    Subclasses must not redeclare these fields; empty-string defaults allow
    constructing without explicit meta while still supporting it.
    """

    schema_version: str = "1.0"
    context_version: str = ""
    context_fingerprint: str = ""
    artifact_id: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
