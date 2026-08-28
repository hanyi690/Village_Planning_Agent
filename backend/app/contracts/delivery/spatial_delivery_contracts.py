"""References and delivery-boundary contracts for spatial artifacts.

The agent graph carries references and bounded read requests. Complete feature
materialization is deliberately represented as a delivery artifact, not as an
LLM-facing state field.
"""
from __future__ import annotations

import math
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class SpatialLayerRef(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    artifact_ref: str = Field(..., min_length=1)
    path: str = Field(..., min_length=1)
    layer_name: str = Field(..., min_length=1)
    driver: str = Field(default="GeoJSON", min_length=1)
    crs: str = ""
    bbox: tuple[float, float, float, float] | None = None
    fields: list[str] = Field(default_factory=list)
    feature_count: int = Field(default=0, ge=0)
    checksum: str = ""

    @field_validator("bbox", mode="before")
    @classmethod
    def accept_json_bbox(cls, value: Any) -> Any:
        return tuple(value) if isinstance(value, list) else value

    @field_validator("bbox")
    @classmethod
    def validate_bbox(
        cls, value: tuple[float, float, float, float] | None
    ) -> tuple[float, float, float, float] | None:
        if value is None:
            return None
        if not all(math.isfinite(item) for item in value):
            raise ValueError("bbox values must be finite")
        west, south, east, north = value
        if west > east or south > north:
            raise ValueError("bbox must be ordered as west, south, east, north")
        return value

    @field_validator("fields")
    @classmethod
    def validate_fields(cls, value: list[str]) -> list[str]:
        if any(not field_name for field_name in value):
            raise ValueError("fields cannot contain empty names")
        if len(value) != len(set(value)):
            raise ValueError("fields must be unique")
        return value


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

    @field_validator("bbox", mode="before")
    @classmethod
    def accept_json_bbox(cls, value: Any) -> Any:
        return tuple(value) if isinstance(value, list) else value

    @model_validator(mode="after")
    def validate_spatial_filter(self) -> "SpatialReadRequest":
        if self.bbox is not None and self.mask is not None:
            raise ValueError("bbox and mask are mutually exclusive")
        if any(fid < 0 for fid in self.fids):
            raise ValueError("fids must be non-negative")
        if any(not bsm for bsm in self.bsms):
            raise ValueError("bsms cannot contain empty values")
        return self


class FeatureBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    layer_ref: SpatialLayerRef
    features: list[dict[str, Any]] = Field(default_factory=list)
    selected_columns: list[str] = Field(default_factory=list)
    complete: bool = False
    feature_count: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def fill_feature_count(self) -> "FeatureBatch":
        if self.feature_count == 0 and self.features:
            self.feature_count = len(self.features)
        return self


class DeliverySpatialSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_layers: dict[str, SpatialLayerRef] = Field(default_factory=dict)
    complete_planned_landuse: SpatialLayerRef | None = None
    planned_overlay_layers: dict[str, SpatialLayerRef] = Field(default_factory=dict)
    constraint_layers: dict[str, SpatialLayerRef] = Field(default_factory=dict)
    change_summary: dict[str, int] = Field(default_factory=dict)
    source_layer_refs: list[SpatialLayerRef] = Field(default_factory=list)
    classification_audit: dict[str, Any] = Field(default_factory=dict)
    parent_digests: dict[str, str] = Field(default_factory=dict)
    quality_report: dict[str, Any] = Field(default_factory=dict)
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
