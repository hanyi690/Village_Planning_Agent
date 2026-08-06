"""Artifact Routes - read-only typed-artifact query endpoints.

Reads from ``FilesystemArtifactStore`` (default base dir ``.run-tmp``).
For the post-L3 chain ``session_id == run_id``, so artifact routes are keyed
by session id.

Endpoints:
1. GET /api/sessions/{session_id}/artifacts                     - list latest refs
2. GET /api/sessions/{session_id}/artifacts/{artifact_type}      - payload + manifest (?version=N)
3. GET /api/sessions/{session_id}/artifacts/{artifact_type}/ref  - artifact ref metadata
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException

from app.modules.ports.artifact_store import ArtifactRef
from app.services.artifact_store import FilesystemArtifactStore

logger = logging.getLogger(__name__)
router = APIRouter()


def _get_store() -> FilesystemArtifactStore:
    return FilesystemArtifactStore()


async def _session_exists(session_id: str) -> bool:
    """Best-effort session existence probe.

    DB lookups are wrapped so a missing/unavailable database degrades to
    "assume the session exists" (return an empty list instead of a 404).
    """
    try:
        from app.database.operations import get_planning_session_async

        return await get_planning_session_async(session_id) is not None
    except Exception:
        return True


def _refs_by_type(
    store: FilesystemArtifactStore, session_id: str, artifact_type: str
) -> list[ArtifactRef]:
    return [
        ref for ref in store.list_by_run(session_id)
        if ref.artifact_type == artifact_type
    ]


def _list_revisions(store: FilesystemArtifactStore, ref: ArtifactRef) -> list[str]:
    """Enumerate revision dir names (e.g. ``v1``, ``v2``) for an artifact."""
    base = Path(store.base_dir) / ref.run_id / "artifacts" / ref.module / ref.artifact_id
    if not base.exists():
        return []
    return sorted(
        d.name for d in base.iterdir() if d.is_dir() and d.name != "__pycache__"
    )


def _revision_to_version(revision: str) -> Optional[int]:
    digits = "".join(ch for ch in revision if ch.isdigit())
    return int(digits) if digits else None


def _ref_with_revision(ref: ArtifactRef, revision: str) -> ArtifactRef:
    return ArtifactRef(
        context_version=ref.context_version,
        artifact_id=ref.artifact_id,
        module=ref.module,
        run_id=ref.run_id,
        artifact_type=ref.artifact_type,
        revision=revision,
        stored_at=ref.stored_at,
    )


async def _resolve_artifact(
    session_id: str, artifact_type: str, version: Optional[int]
) -> tuple[ArtifactRef, dict, dict]:
    store = _get_store()
    refs = _refs_by_type(store, session_id, artifact_type)
    if not refs:
        raise HTTPException(
            status_code=404,
            detail=f"Artifact type not found: {artifact_type} for session {session_id}",
        )
    latest = refs[0]
    target = latest
    if version is not None:
        rev_map = {
            _revision_to_version(rev): rev for rev in _list_revisions(store, latest)
        }
        revision = rev_map.get(version)
        if revision is None:
            supported = sorted(rev_map)
            raise HTTPException(
                status_code=404,
                detail=(
                    f"Version {version} not stored for {artifact_type}; "
                    f"supported versions: {supported or ['latest']}"
                ),
            )
        target = _ref_with_revision(latest, revision)
    payload = store.retrieve(target)
    manifest = store.read_manifest(target)
    return target, payload, manifest


@router.get("/api/sessions/{session_id}/artifacts")
async def list_session_artifacts(session_id: str):
    """List the latest artifact refs stored under a session (run)."""
    store = _get_store()
    refs = store.list_by_run(session_id)
    if not refs and not await _session_exists(session_id):
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")
    return {
        "session_id": session_id,
        "artifacts": [ref.model_dump(mode="json") for ref in refs],
        "count": len(refs),
    }


@router.get("/api/sessions/{session_id}/artifacts/{artifact_type}")
async def get_session_artifact(
    session_id: str, artifact_type: str, version: Optional[int] = None
):
    """Return an artifact payload + manifest, optionally pinned to ``?version=N``."""
    target, payload, manifest = await _resolve_artifact(
        session_id, artifact_type, version
    )
    return {
        "session_id": session_id,
        "artifact_type": artifact_type,
        "revision": target.revision,
        "artifact_ref": target.model_dump(mode="json"),
        "payload": payload,
        "manifest": manifest,
    }


@router.get("/api/sessions/{session_id}/artifacts/{artifact_type}/ref")
async def get_session_artifact_ref(
    session_id: str, artifact_type: str, version: Optional[int] = None
):
    """Return artifact ref metadata (manifest), optionally pinned to ``?version=N``."""
    target, _, manifest = await _resolve_artifact(session_id, artifact_type, version)
    return {
        "session_id": session_id,
        "artifact_type": artifact_type,
        "revision": target.revision,
        "artifact_ref": target.model_dump(mode="json"),
        "manifest": manifest,
    }


__all__ = ["router"]
