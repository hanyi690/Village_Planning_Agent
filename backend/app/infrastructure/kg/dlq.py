"""Dead Letter Queue — structured DLQ with three categories.

Categories:
    geometry:   Geometry validation failed (must_be_valid = False)
    mapping:    Code mapping not found (unmapped)
    review:     Manual decision required (manual/low-confidence)

Each entry preserves the raw feature + reason + source layer.
Pipeline does not block — DLQ is collected and reported.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class DlqCategory(str, Enum):
    """DLQ entry category — determines the downstream disposition."""
    GEOMETRY = "geometry"
    MAPPING = "mapping"
    REVIEW = "review"


class DlqEntry(BaseModel):
    """A single DLQ entry — preserves the raw feature + reason for replay.

    Attributes:
        category: DLQ category (geometry/mapping/review)
        reason: Human-readable explanation of the failure
        source_layer: The gis_type_ref of the source layer
        raw_feature: The raw feature dict (GeoJSON Feature or similar)
        bsm: Optional identifier code for traceability
    """
    category: DlqCategory
    reason: str
    source_layer: str
    raw_feature: dict[str, Any] = Field(default_factory=dict)
    bsm: str = ""


class DlqReport(BaseModel):
    """Aggregated DLQ report — collects entries across a pipeline run.

    Provides category breakdown and summary statistics.
    """
    entries: list[DlqEntry] = Field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.entries)

    def add(self, entry: DlqEntry) -> None:
        self.entries.append(entry)

    def merge(self, other: DlqReport) -> None:
        self.entries.extend(other.entries)

    def by_category(self, category: DlqCategory) -> list[DlqEntry]:
        return [e for e in self.entries if e.category == category]

    def summary(self) -> dict[str, Any]:
        counts = {cat.value: 0 for cat in DlqCategory}
        for e in self.entries:
            counts[e.category.value] += 1
        return {
            "total": self.total,
            "by_category": counts,
        }


__all__ = [
    "DlqCategory",
    "DlqEntry",
    "DlqReport",
]