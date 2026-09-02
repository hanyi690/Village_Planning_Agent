"""Immutable lightweight manifest for normalized DATA inputs."""

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
    crs: str = ""
    feature_count: int = 0
    digest: str
    source: str = ""
    source_uris: tuple[str, ...] = ()
    source_feature_ids: tuple[str, ...] = ()
    source_feature_count: int = 0
    source_feature_digest: str = ""


class SessionDataSnapshot(BaseModel):
    """Frozen inventory; feature payloads remain in DATA products/CAS."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    snapshot_id: str
    session_id: str
    village_name: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    collections: tuple[CollectionSnapshot, ...] = ()
    source_refs: tuple[str, ...] = ()
    digest: str

    @classmethod
    def from_data_catalog(
        cls,
        catalog: Any,
        *,
        session_id: str,
        village_name: str = "",
        source: str = "data_catalog",
    ) -> "SessionDataSnapshot":
        snapshot = getattr(catalog, "snapshot", catalog)
        datasets = list(getattr(snapshot, "datasets", None) or ())
        primary = getattr(snapshot, "dataset", None)
        if primary is not None and not datasets:
            datasets = [primary]
        features = list(getattr(snapshot, "features", None) or ())
        by_dataset: dict[str, list[Any]] = {}
        for feature in features:
            by_dataset.setdefault(str(getattr(feature, "dataset_ref", "") or ""), []).append(feature)
        collections: list[CollectionSnapshot] = []
        for dataset in datasets:
            dataset_ref = str(getattr(dataset, "dataset_ref", "") or "")
            rows = by_dataset.get(dataset_ref, [])
            layers = sorted({str(getattr(row, "layer_ref", "") or "") for row in rows})
            for layer in layers or [""]:
                layer_rows = [row for row in rows if str(getattr(row, "layer_ref", "") or "") == layer]
                ids = [str(getattr(row, "source_feature_ref", "") or "") for row in layer_rows]
                material = {
                    "dataset_ref": dataset_ref,
                    "layer_ref": layer,
                    "feature_ids": ids,
                    "feature_digests": [str(getattr(row, "source_feature_digest", "") or "") for row in layer_rows],
                }
                digest = "sha256:" + hashlib.sha256(
                    json.dumps(material, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
                ).hexdigest()
                collections.append(CollectionSnapshot(
                    key=f"{dataset_ref}:{layer or 'all'}",
                    crs=str(getattr(dataset, "crs", "") or ""),
                    feature_count=len(layer_rows),
                    digest=digest,
                    source=source,
                    source_uris=tuple(str(item) for item in (getattr(dataset, "source_uris", None) or ()) if str(item)),
                    source_feature_ids=tuple(ids),
                    source_feature_count=len(ids),
                    source_feature_digest=digest,
                ))
        if not collections:
            fallback = str(getattr(snapshot, "digest", "") or "") or "sha256:" + hashlib.sha256(b"data_catalog").hexdigest()
            collections.append(CollectionSnapshot(key="data_catalog", digest=fallback, source=source))
        digest = "sha256:" + hashlib.sha256(
            json.dumps(
                {"catalog_digest": str(getattr(snapshot, "digest", "") or ""), "collections": [item.model_dump(mode="json") for item in collections]},
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        return cls(
            snapshot_id=str(getattr(snapshot, "snapshot_id", "") or f"data-{session_id}-{digest.removeprefix('sha256:')[:16]}"),
            session_id=session_id,
            village_name=village_name,
            collections=tuple(collections),
            source_refs=tuple(dict.fromkeys([
                source,
                *(str(item) for dataset in datasets for item in (getattr(dataset, "source_uris", None) or ()) if str(item)),
            ])),
            digest=digest,
        )


__all__ = ["CollectionSnapshot", "SessionDataSnapshot"]
