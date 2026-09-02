"""Provider-run ownership and publication contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ProviderRunLease(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    run_ref: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    owner_id: str = Field(min_length=1)
    fencing_token: int = Field(ge=1)
    acquired_at: datetime
    expires_at: datetime
    status: Literal["ACTIVE", "EXPIRED", "RELEASED"]


class ProviderRunRecovery(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    run_ref: str
    provider: str
    previous_fencing_token: int = 0
    status: Literal["NOT_FOUND", "ACTIVE", "ABANDONED", "RECOVERED"]
    staging_path: str = ""
    reason: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


__all__ = ["ProviderRunLease", "ProviderRunRecovery"]
