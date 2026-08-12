"""Typed carrier for stage-local progress during root migration."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class WorkflowProgress(BaseModel):
    """Serializable stage view owned by the workflow-progress artifact.

    Dynamic legacy stage fields live under ``stage_payload`` while the
    migration is in progress. They are deliberately not model fields: this
    keeps the carrier bounded without changing the local state seen by the
    existing stage nodes.
    """

    model_config = ConfigDict(extra="forbid")

    session_id: str = ""
    run_id: str = ""
    branch_id: str = "main"
    artifact_refs: dict[str, Any] = Field(default_factory=dict)
    stage_payload: dict[str, Any] = Field(default_factory=dict)


__all__ = ["WorkflowProgress"]
