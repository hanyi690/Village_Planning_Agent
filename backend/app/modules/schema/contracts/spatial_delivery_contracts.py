"""References and delivery-boundary contracts for spatial artifacts.

The agent graph carries references and bounded read requests. Complete feature
materialization is deliberately represented as a delivery artifact, not as an
LLM-facing state field.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class SpatialLayerRef(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    artifact_ref: str
    path: str
    layer_name: str
    driver: str = "GeoJSON"
    crs: str = ""
    bbox: tuple[float, float, float, float] | None = None
    fields: list[str] = Field(default_factory=list)
    feature_count: int = 0
    checksum: str = ""


class SpatialReadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    layer_ref: SpatialLayerRef
    columns: list[str] = Field(default_factory=list)
    bbox: tuple[float, float, float, float] | None = None
    mask: dict[str, Any] | None = None
    where: str | None = None
    fids: list[int] = Field(default_factory=list)
    bsms: list[str] = Field(default_factory=list)
    read_geometry: bool = True


class FeatureBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    layer_ref: SpatialLayerRef
    features: list[dict[str, Any]] = Field(default_factory=list)
    selected_columns: list[str] = Field(default_factory=list)
    complete: bool = False


class DeliverySpatialSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_layers: dict[str, SpatialLayerRef] = Field(default_factory=dict)
    complete_planned_landuse: SpatialLayerRef | None = None
    planned_overlay_layers: dict[str, SpatialLayerRef] = Field(default_factory=dict)
    constraint_layers: dict[str, SpatialLayerRef] = Field(default_factory=dict)
    change_summary: dict[str, int] = Field(default_factory=dict)
    source_layer_refs: list[SpatialLayerRef] = Field(default_factory=list)
    classification_audit: dict[str, Any] = Field(default_factory=dict)
    checksum: str = ""
    provenance: dict[str, Any] = Field(default_factory=dict)
    delivery_status: Literal["complete", "partial", "diagnostic_only"] = "partial"
    statutory_complete: bool = False


__all__ = [
    "SpatialLayerRef",
    "SpatialReadRequest",
    "FeatureBatch",
    "DeliverySpatialSnapshot",
]
