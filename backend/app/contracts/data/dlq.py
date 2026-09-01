"""Data-ingestion dead-letter contracts.

These contracts belong to DATA.  KG and Evidence may consume the records, but
DATA must not import either infrastructure layer merely to report a rejected
source record.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class DlqCategory(str, Enum):
    GEOMETRY = "geometry"
    MAPPING = "mapping"
    REVIEW = "review"


class DlqEntry(BaseModel):
    category: DlqCategory
    reason: str
    source_layer: str
    raw_feature: dict[str, Any] = Field(default_factory=dict)
    bsm: str = ""


class DlqReport(BaseModel):
    entries: list[DlqEntry] = Field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.entries)

    def add(self, entry: DlqEntry) -> None:
        self.entries.append(entry)

    def merge(self, other: "DlqReport") -> None:
        self.entries.extend(other.entries)

    def by_category(self, category: DlqCategory) -> list[DlqEntry]:
        return [entry for entry in self.entries if entry.category == category]

    def summary(self) -> dict[str, Any]:
        counts = {category.value: 0 for category in DlqCategory}
        for entry in self.entries:
            counts[entry.category.value] += 1
        return {"total": self.total, "by_category": counts}


__all__ = ["DlqCategory", "DlqEntry", "DlqReport"]
