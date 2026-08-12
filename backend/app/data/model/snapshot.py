"""Immutable data manifest owned by the data layer."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class CollectionSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    key: str
    media_type: str = "application/geo+json"
    crs: str = "EPSG:4326"
    feature_count: int = 0
    digest: str
    source: str = ""


class SessionDataSnapshot(BaseModel):
    """Frozen inventory of session inputs; it never embeds feature payloads."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    snapshot_id: str
    session_id: str
    village_name: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    collections: tuple[CollectionSnapshot, ...] = ()
    source_refs: tuple[str, ...] = ()
    digest: str

    @classmethod
    def from_bundle(
        cls,
        bundle: Any,
        *,
        session_id: str,
        source: str = "data_catalog",
    ) -> "SessionDataSnapshot":
        if bundle is None or not hasattr(bundle, "to_geojson_dict"):
            raise ValueError("SessionDataSnapshot requires a data-layer bundle")
        payloads = bundle.to_geojson_dict()
        collections: list[CollectionSnapshot] = []
        for key, value in sorted(payloads.items()):
            if not str(key).endswith("_geojson") or not isinstance(value, dict):
                continue
            features = value.get("features") or []
            canonical = json.dumps(
                value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
            collections.append(
                CollectionSnapshot(
                    key=str(key),
                    crs=str((value.get("crs") or {}).get("name") or "EPSG:4326"),
                    feature_count=len(features),
                    digest="sha256:" + hashlib.sha256(canonical).hexdigest(),
                    source=source,
                )
            )
        manifest = [item.model_dump(mode="json") for item in collections]
        digest = "sha256:" + hashlib.sha256(
            json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        village_name = str(getattr(bundle, "village_name", "") or "")
        snapshot_id = f"data-{session_id}-{digest.removeprefix('sha256:')[:16]}"
        return cls(
            snapshot_id=snapshot_id,
            session_id=session_id,
            village_name=village_name,
            collections=tuple(collections),
            source_refs=(source,),
            digest=digest,
        )

    def collection(self, key: str) -> CollectionSnapshot | None:
        return next((item for item in self.collections if item.key == key), None)


__all__ = ["CollectionSnapshot", "SessionDataSnapshot"]
