"""Application query for the map-layer collection from spatial snapshots."""

from __future__ import annotations

from typing import Any, Protocol


class SnapshotStorePort(Protocol):
    """Reads the spatial snapshot and render-layer artifacts for a session."""

    async def snapshot(self, session_id: str) -> Any | None: ...

    async def layers(self, session_id: str) -> Any | None: ...


class _SnapshotStore:
    async def snapshot(self, session_id: str) -> Any | None:
        from app.application.queries.artifacts import artifact_queries

        return await artifact_queries.read(session_id, "delivery_spatial_snapshot")

    async def layers(self, session_id: str) -> Any | None:
        from app.application.queries.artifacts import artifact_queries

        return await artifact_queries.read(session_id, "render_layers")


async def get_map_layer_collection(
    session_id: str,
    *,
    snapshot_store: SnapshotStorePort,
) -> dict[str, object]:
    """Return the map-layer collection as a serializable dict."""

    from app.application.projections.delivery import _layer_view

    snapshot = await snapshot_store.snapshot(session_id)
    layers_artifact = await snapshot_store.layers(session_id)
    if snapshot is None or layers_artifact is None:
        return {"session_id": session_id, "layers": []}
    raw = layers_artifact.payload if hasattr(layers_artifact, "payload") else None
    if not isinstance(raw, list):
        return {"session_id": session_id, "layers": []}
    snapshot_ref = snapshot.artifact_ref
    if not isinstance(snapshot_ref, dict):
        snapshot_ref = {}
    snapshot_payload = snapshot.payload
    return {
        "session_id": session_id,
        "snapshot_checksum": str(snapshot_ref.get("digest") or ""),
        "delivery_status": (
            str(snapshot_payload.get("delivery_status"))
            if isinstance(snapshot_payload, dict)
            and snapshot_payload.get("delivery_status")
            else None
        ),
        "layers": [
            _layer_view(layer).model_dump(mode="json")
            for layer in raw
            if isinstance(layer, dict)
        ],
    }


__all__ = ["SnapshotStorePort", "get_map_layer_collection"]
