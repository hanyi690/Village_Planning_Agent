"""Snapshot data quality report owned by the data layer."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.data.catalog.collection_registry import CollectionRecord
from app.data.model.snapshot import SessionDataSnapshot


class DataQualityReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    collection_checks: dict[str, dict[str, Any]] = Field(default_factory=dict)
    total_features: int = 0
    issues: list[str] = Field(default_factory=list)
    frozen: bool = False


def build_data_quality_report(
    snapshot: SessionDataSnapshot,
    records: list[CollectionRecord] | None = None,
    *,
    frozen: bool = False,
) -> DataQualityReport:
    registered = {record.collection_id for record in (records or [])}
    checks: dict[str, dict[str, Any]] = {}
    issues: list[str] = []
    total = 0
    for item in snapshot.collections:
        checks[item.key] = {
            "feature_count": item.feature_count,
            "crs": item.crs,
            "digest": item.digest,
            "registered": item.key in registered,
        }
        total += item.feature_count
        if item.feature_count == 0:
            issues.append(f"collection '{item.key}' is empty")
    return DataQualityReport(
        collection_checks=checks,
        total_features=total,
        issues=issues,
        frozen=frozen,
    )


__all__ = ["DataQualityReport", "build_data_quality_report"]
