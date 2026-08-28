"""Immutable media and visual evidence contracts."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from app.contracts.base import JsonObject, StrictContractModel


class ImageIngestRequest(StrictContractModel):
    """Provider-neutral metadata needed to register one image artifact."""

    source_ref: str
    mime_type: str
    storage_ref: str = ""
    file_name: str = ""
    parent_document_ref: str | None = None
    page: int | None = None
    crs: str | None = None
    bbox: list[float] | None = None
    captured_at: str | None = None
    preprocessing_ref: str | None = None


class ImageArtifact(StrictContractModel):
    """Content-addressed media metadata; the image bytes stay in storage."""

    artifact_ref: str
    sha256: str
    storage_ref: str
    mime_type: str
    width: int
    height: int
    source_ref: str
    file_name: str = ""
    parent_document_ref: str | None = None
    page: int | None = None
    crs: str | None = None
    bbox: list[float] | None = None
    captured_at: str | None = None
    preprocessing_ref: str | None = None


class VisualAnalysisRequest(StrictContractModel):
    """Bounded, provider-neutral request for typed visual extraction."""

    dimension: str
    target_ref: str | None = None
    region_bbox: list[float] | None = None
    detail_level: Literal["low", "standard", "high"] = "standard"
    evidence_refs: list[str] = Field(default_factory=list)


class ImageEvidence(StrictContractModel):
    """Typed OCR/layout/legend/label evidence derived from an image."""

    evidence_id: str
    image_ref: str
    page: int | None = None
    region_bbox: list[float] | None = None
    ocr_text_ref: str | None = None
    caption: str = ""
    layout: list[JsonObject] = Field(default_factory=list)
    visual_elements: list[JsonObject] = Field(default_factory=list)
    legend: list[JsonObject] = Field(default_factory=list)
    labels: list[JsonObject] = Field(default_factory=list)
    detection_labels: list[JsonObject] = Field(default_factory=list)
    confidence: float
    spatial_status: Literal["resolved", "ambiguous", "unresolved"]
    temporal_status: Literal["resolved", "ambiguous", "unresolved"]
    review_status: Literal["accepted", "needs_review", "human_required"]


class VisualFact(StrictContractModel):
    """A typed observation that cannot itself mutate spatial decisions."""

    dimension: str
    fact_type: str
    subject: str
    predicate: str
    object: str
    evidence_refs: list[str] = Field(default_factory=list)
    confidence: float
    human_required: bool
    target_ref: str | None = None


class VisualReview(StrictContractModel):
    """Post-execution visual review linked to an existing planning target."""

    target_ref: str = ""
    target_id: str | None = None
    planning_status: str
    evidence_refs: list[str] = Field(default_factory=list)
    issue: str
    adjustment_refs: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_target_reference(self) -> "VisualReview":
        if not self.target_ref and not self.target_id:
            raise ValueError("visual review requires target_ref or target_id")
        return self


__all__ = [
    "ImageArtifact",
    "ImageEvidence",
    "ImageIngestRequest",
    "VisualAnalysisRequest",
    "VisualFact",
    "VisualReview",
]
