"""GET /sessions/{session_id}/artifacts/{artifact_key} transport."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.application.queries.artifacts import ArtifactNotFoundError, artifact_queries
from app.application.queries.workflow_state import load_workflow_state


router = APIRouter(prefix="/api/v1", tags=["Stable v1"])


@router.get("/sessions/{session_id}/artifacts")
async def list_artifacts(session_id: str) -> dict[str, object]:
    """List artifact references present in the current checkpoint.

    The client uses this index before reading payloads, so an absent artifact
    is represented as a normal state instead of a burst of expected 404s.
    """

    state = await load_workflow_state(session_id)
    refs = state.get("artifact_refs") if state else {}
    artifacts = [
        {"artifact_key": str(key), "artifact_ref": value}
        for key, value in (refs or {}).items()
        if isinstance(value, dict)
    ]
    return {"session_id": session_id, "artifacts": artifacts}


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
