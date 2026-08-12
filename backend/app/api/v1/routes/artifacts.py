"""GET /sessions/{session_id}/artifacts/{artifact_key} transport."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.application.queries.artifacts import ArtifactNotFoundError, artifact_queries


router = APIRouter(prefix="/api/v1", tags=["Stable v1"])


@router.get("/sessions/{session_id}/artifacts/{artifact_key}")
async def get_artifact(session_id: str, artifact_key: str) -> dict[str, object]:
    try:
        artifact = await artifact_queries.read(session_id, artifact_key)
    except ArtifactNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if artifact is None:
        raise HTTPException(status_code=404, detail="artifact is not present in current checkpoint")
    return artifact.model_dump(mode="json")


__all__ = ["get_artifact", "router"]
