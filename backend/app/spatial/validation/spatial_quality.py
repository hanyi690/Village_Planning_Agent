"""Spatial geometry quality checks: validity, repair, area measurement."""

from __future__ import annotations

from typing import Any, Iterable

from pydantic import BaseModel, ConfigDict, Field


class SpatialQualityReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    checked_count: int = 0
    valid_count: int = 0
    invalid_count: int = 0
    repaired_count: int = 0
    empty_count: int = 0
    total_area_ha: float = 0.0
    issues: list[str] = Field(default_factory=list)


def _geometry_of(item: Any) -> Any:
    if isinstance(item, dict):
        return item.get("geometry")
    return getattr(item, "geometry", None)


def spatial_quality_check(geometries: Iterable[Any]) -> SpatialQualityReport:
    """Validate/repair geometries with shapely make_valid and the area engine."""
    from shapely.geometry import shape

    from app.spatial.model.area_engine import calculate_area_ha

    issues: list[str] = []
    checked = valid = invalid = repaired = empty = 0
    total_area_ha = 0.0
    for item in geometries:
        geometry = _geometry_of(item)
        if not geometry:
            empty += 1
            continue
        try:
            parsed = shape(geometry)
            if parsed.is_empty:
                empty += 1
                continue
            checked += 1
            if not parsed.is_valid:
                invalid += 1
                try:
                    from shapely.validation import make_valid

                    repaired_geom = make_valid(parsed)
                except Exception as exc:
                    issues.append(f"make_valid failed: {exc}")
                    continue
                if repaired_geom is None or repaired_geom.is_empty or not repaired_geom.is_valid:
                    issues.append("geometry remains invalid after make_valid")
                    continue
                parsed = repaired_geom
                repaired += 1
            else:
                valid += 1
            total_area_ha += float(calculate_area_ha(parsed) or 0.0)
        except Exception as exc:
            issues.append(f"geometry parse failed: {exc}")
    return SpatialQualityReport(
        checked_count=checked,
        valid_count=valid,
        invalid_count=invalid,
        repaired_count=repaired,
        empty_count=empty,
        total_area_ha=round(total_area_ha, 6),
        issues=issues,
    )


__all__ = ["SpatialQualityReport", "spatial_quality_check"]
