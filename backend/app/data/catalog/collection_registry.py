"""Import-light collection registry for session data ownership."""

from __future__ import annotations

import warnings
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.data.model.snapshot import CollectionSnapshot


with warnings.catch_warnings():
    warnings.simplefilter("ignore")

    class CollectionRecord(BaseModel):
        model_config = ConfigDict(frozen=True, extra="forbid")

        collection_id: str
        schema: dict[str, Any] = Field(default_factory=dict)
        crs: str = "EPSG:4326"
        digest: str = ""
        source: str = ""
        feature_count: int = 0

    @classmethod
    def from_snapshot(cls, snapshot: CollectionSnapshot) -> "CollectionRecord":
        return cls(
            collection_id=snapshot.key,
            crs=snapshot.crs,
            digest=snapshot.digest,
            source=snapshot.source,
            feature_count=snapshot.feature_count,
        )


class CollectionRegistry:
    def __init__(self) -> None:
        self._records: dict[str, CollectionRecord] = {}

    def register(
        self,
        collection_id: str,
        schema: dict[str, Any] | None = None,
        crs: str = "EPSG:4326",
        digest: str = "",
        source: str = "",
        feature_count: int = 0,
    ) -> CollectionRecord:
        record = CollectionRecord(
            collection_id=collection_id,
            schema=dict(schema or {}),
            crs=crs,
            digest=digest,
            source=source,
            feature_count=feature_count,
        )
        self._records[collection_id] = record
        return record

    def register_snapshot(self, snapshot: CollectionSnapshot) -> CollectionRecord:
        return self.register(
            collection_id=snapshot.key,
            crs=snapshot.crs,
            digest=snapshot.digest,
            source=snapshot.source,
            feature_count=snapshot.feature_count,
        )

    def get(self, collection_id: str) -> CollectionRecord | None:
        return self._records.get(collection_id)

    def keys(self) -> list[str]:
        return list(self._records.keys())

    def all(self) -> list[CollectionRecord]:
        return list(self._records.values())

    def __len__(self) -> int:
        return len(self._records)


__all__ = ["CollectionRecord", "CollectionRegistry"]
