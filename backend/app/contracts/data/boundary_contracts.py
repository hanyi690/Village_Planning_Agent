"""Immutable contracts for DATA-owned spatial query scopes."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


BoundaryScopeMode = Literal["admitted_boundary", "polygonized_admin_boundary"]


def _digest(value: Any) -> str:
    raw = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


class BoundaryScopeArtifact(BaseModel):
    """The only DATA product allowed to scope external spatial queries."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    scope_ref: str = Field(min_length=1)
    source_snapshot_ref: str = Field(min_length=1)
    source_dataset_ref: str = Field(min_length=1)
    source_feature_refs: tuple[str, ...] = Field(min_length=1)
    source_representation_refs: tuple[str, ...] = Field(min_length=1)
    source_digest: str = Field(min_length=1)
    boundary_digest: str = Field(min_length=1)
    geometry: dict[str, Any]
    geometry_type: Literal["Polygon", "MultiPolygon"]
    normalized_crs: str = Field(default="EPSG:4326", min_length=1)
    mode: BoundaryScopeMode
    topology_repair_trace: tuple[str, ...] = ()
    query_geometry_digest: str = ""

    def model_post_init(self, __context: Any) -> None:
        if not self.query_geometry_digest:
            object.__setattr__(self, "query_geometry_digest", _digest(self.geometry))


__all__ = ["BoundaryScopeArtifact", "BoundaryScopeMode"]
