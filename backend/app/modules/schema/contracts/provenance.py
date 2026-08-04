from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field


class Provenance(BaseModel):
    source: str
    run_id: str
    module: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    trace: list[str] = Field(default_factory=list)
    natural_language_description: str | None = None
    spatial_hint: str | None = None
    reasoning_trace: str | None = None
    raw_text: str | None = None


class SemanticMetadata(BaseModel):
    natural_language_description: str = ""
    spatial_hint: str = ""
    reasoning_trace: str = ""
    raw_text: str = ""
