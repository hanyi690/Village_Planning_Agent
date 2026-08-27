"""Small immutable contracts for the project-cognition boundary."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ProjectCognitionSnapshot(_Frozen):
    project_ref: str = ""
    session_id: str = ""
    revision: str = ""
    spatial_scope: dict[str, Any] = Field(default_factory=dict)
    time_scope: dict[str, Any] = Field(default_factory=dict)
    snapshots: dict[str, Any] = Field(default_factory=dict)
    available_data: dict[str, Any] = Field(default_factory=dict)
    quality: dict[str, Any] = Field(default_factory=dict)
    cognition_digest: str


__all__ = ["ProjectCognitionSnapshot"]
