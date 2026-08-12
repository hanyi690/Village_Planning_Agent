"""Freeze a session data snapshot; no implicit refresh after freeze."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict

from app.data.catalog.collection_registry import CollectionRecord, CollectionRegistry
from app.data.model.snapshot import SessionDataSnapshot
from app.data.snapshots.data_quality import DataQualityReport, build_data_quality_report


class FrozenSessionSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)

    snapshot: SessionDataSnapshot
    registry: CollectionRegistry
    quality: DataQualityReport
    frozen: bool = True

    def refresh(self) -> "FrozenSessionSnapshot":
        raise RuntimeError("frozen session snapshot does not support refresh")

    @property
    def session_id(self) -> str:
        return self.snapshot.session_id

    @property
    def digest(self) -> str:
        return self.snapshot.digest

    @property
    def collections(self) -> tuple[CollectionRecord, ...]:
        return tuple(self.registry.all())


def freeze_session_snapshot(manifest: Any, workspace: Any) -> FrozenSessionSnapshot:
    snapshot = getattr(workspace, "snapshot", None)
    if manifest is not None and hasattr(manifest, "to_geojson_dict"):
        session_id = snapshot.session_id if snapshot is not None else ""
        snapshot = SessionDataSnapshot.from_bundle(manifest, session_id=session_id)
    if snapshot is None or not isinstance(snapshot, SessionDataSnapshot):
        raise ValueError("freeze_session_snapshot requires a manifest or workspace snapshot")

    registry = CollectionRegistry()
    for item in snapshot.collections:
        registry.register_snapshot(item)
    quality = build_data_quality_report(snapshot, registry.all(), frozen=True)
    return FrozenSessionSnapshot(
        snapshot=snapshot,
        registry=registry,
        quality=quality,
        frozen=True,
    )


__all__ = ["FrozenSessionSnapshot", "freeze_session_snapshot"]
