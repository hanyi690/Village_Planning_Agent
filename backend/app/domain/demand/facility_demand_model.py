"""Typed demand snapshots consumed by network facility-service evaluation."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable

from pydantic import BaseModel, ConfigDict, Field, computed_field


class FacilityDemandPoint(BaseModel):
    """One demand location and the facility types allowed to serve it."""

    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)

    demand_id: str = Field(min_length=1)
    geometry_wkt: str = Field(min_length=1)
    crs: str = Field(default="EPSG:4326", min_length=1)
    demand_value: float = Field(default=1.0, ge=0)
    demand_unit: str = "person/day"
    facility_types: tuple[str, ...] = ()

    @classmethod
    def from_feature(
        cls,
        feature: Any,
        *,
        demand_id: str = "",
        demand_value: float | None = None,
        demand_unit: str = "person/day",
        facility_types: Iterable[str] = (),
    ) -> "FacilityDemandPoint":
        geometry = getattr(feature, "geometry", None)
        if geometry is None and isinstance(feature, dict):
            geometry = feature.get("geometry", feature)
        from shapely.geometry import shape

        point_id = demand_id or str(
            getattr(feature, "demand_id", None)
            or getattr(feature, "id", None)
            or ((feature.get("properties") or {}).get("demand_id") if isinstance(feature, dict) else "")
            or "demand"
        )
        properties = feature.get("properties", {}) if isinstance(feature, dict) else {}
        return cls(
            demand_id=point_id,
            geometry_wkt=shape(geometry).wkt if isinstance(geometry, dict) else str(geometry),
            crs=str(getattr(feature, "crs", None) or properties.get("crs") or "EPSG:4326"),
            demand_value=(
                float(demand_value)
                if demand_value is not None
                else float(properties.get("demand_value", properties.get("weight", 1.0)))
            ),
            demand_unit=str(properties.get("demand_unit", demand_unit)),
            facility_types=tuple(sorted({str(item) for item in facility_types if str(item)})),
        )


DemandPoint = FacilityDemandPoint


class DemandSnapshot(BaseModel):
    """Versioned, immutable demand input for a facility-service relation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    demand_ref: str = Field(min_length=1)
    points: tuple[FacilityDemandPoint, ...] = ()
    source_refs: tuple[str, ...] = ()
    diagnostics: tuple[str, ...] = ()

    @computed_field
    @property
    def fingerprint(self) -> str:
        payload = self.model_dump(mode="json", exclude={"fingerprint"})
        return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()

    @property
    def total_demand(self) -> float:
        return sum(item.demand_value for item in self.points)


def build_demand_snapshot(
    demand_ref: str,
    points: Iterable[FacilityDemandPoint],
    *,
    source_refs: Iterable[str] = (),
) -> DemandSnapshot:
    return DemandSnapshot(
        demand_ref=demand_ref,
        points=tuple(sorted(points, key=lambda item: item.demand_id)),
        source_refs=tuple(sorted({str(item) for item in source_refs if str(item)})),
    )


__all__ = [
    "DemandPoint",
    "DemandSnapshot",
    "FacilityDemandPoint",
    "build_demand_snapshot",
]
