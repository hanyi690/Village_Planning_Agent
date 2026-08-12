"""Explicit artifact reads for application projections."""

from __future__ import annotations

from typing import Mapping

from pydantic import BaseModel, ConfigDict, Field

from app.application.queries.workflow_state import load_workflow_state
from app.infrastructure.artifacts.runtime import ARTIFACT_KEYS, load_artifact


class ArtifactNotFoundError(LookupError):
    """The session or requested explicit artifact does not exist."""


class ArtifactRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str
    artifact_key: str
    artifact_ref: dict[str, object]
    payload: dict[str, object] | list[object]


class ArtifactQueryService:
    async def read(self, session_id: str, artifact_key: str) -> ArtifactRead | None:
        if artifact_key not in ARTIFACT_KEYS:
            raise ArtifactNotFoundError("unknown artifact key")
        state = await load_workflow_state(session_id)
        if not state:
            return None
        raw_ref = (state.get("artifact_refs") or {}).get(artifact_key)
        if not isinstance(raw_ref, dict):
            return None
        payload = load_artifact(dict(state), artifact_key)
        if hasattr(payload, "model_dump"):
            payload = payload.model_dump(mode="json")
        if not isinstance(payload, (dict, list)):
            return None
        return ArtifactRead(
            session_id=session_id,
            artifact_key=artifact_key,
            artifact_ref=dict(raw_ref),
            payload=payload,
        )


artifact_queries = ArtifactQueryService()


__all__ = ["ArtifactNotFoundError", "ArtifactQueryService", "ArtifactRead", "artifact_queries"]
