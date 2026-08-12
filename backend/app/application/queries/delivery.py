"""Application query for the delivery projection from the manifest artifact."""

from __future__ import annotations

from typing import Any, Protocol


class ArtifactStorePort(Protocol):
    """Reads one explicit content-addressed artifact for a session."""

    async def read(self, session_id: str, artifact_key: str) -> Any | None: ...


class _ArtifactStore:
    async def read(self, session_id: str, artifact_key: str) -> Any | None:
        from app.application.queries.artifacts import artifact_queries

        return await artifact_queries.read(session_id, artifact_key)


async def get_delivery_projection(
    session_id: str,
    *,
    artifact_store: ArtifactStorePort,
) -> dict[str, object]:
    """Return the delivery projection as a serializable dict."""

    manifest = await artifact_store.read(session_id, "delivery_manifest")
    if manifest is None or not isinstance(getattr(manifest, "payload", None), dict):
        return {
            "session_id": session_id,
            "available": False,
            "delivery_status": None,
            "deferral_summary": {},
            "manifest_ref": {},
        }
    payload = manifest.payload
    deliverables = [
        item for item in payload.get("deliverables") or [] if isinstance(item, dict)
    ]
    manifest_ref = manifest.artifact_ref
    if not isinstance(manifest_ref, dict):
        manifest_ref = {}
    return {
        "session_id": session_id,
        "available": True,
        "delivery_status": (
            str(payload.get("delivery_status"))
            if payload.get("delivery_status") else None
        ),
        "statutory_complete": bool(payload.get("statutory_complete")),
        "deferral_summary": dict(payload.get("deferral_summary") or {}),
        "manifest_ref": dict(manifest_ref),
        "downloads": [
            str(item.get("path")) for item in deliverables if item.get("path")
        ],
    }


__all__ = ["ArtifactStorePort", "get_delivery_projection"]
