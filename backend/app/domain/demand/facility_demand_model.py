"""Typed demand snapshots consumed by network facility-service evaluation."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable, Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator


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


class DemandSnapshot(BaseModel):
    """Versioned, immutable demand input for a facility-service relation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    demand_ref: str = Field(min_length=1)
    points: tuple[FacilityDemandPoint, ...] = ()
    source_refs: tuple[str, ...] = ()
    source_binding: str = ""
    crs: str = "EPSG:4326"
    time_slice: str = ""
    version: str = ""
    declared_total_demand: float | None = Field(default=None, ge=0)
    availability: Literal["ready", "pending", "blocked"] = "pending"
    diagnostics: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_snapshot(self) -> "DemandSnapshot":
        points = tuple(sorted(self.points, key=lambda item: item.demand_id))
        object.__setattr__(self, "points", points)
        if self.declared_total_demand is not None and abs(
            self.declared_total_demand - sum(item.demand_value for item in points)
        ) > 1e-9:
            raise ValueError("declared_total_demand does not match demand points")
        diagnostics = set(self.diagnostics)
        if any(item.demand_value < 0 for item in points):
            diagnostics.add("negative_demand")
        if not self.source_binding or not self.source_refs:
            diagnostics.add("demand_source_binding_missing")
        if not self.version:
            diagnostics.add("demand_version_missing")
        object.__setattr__(self, "diagnostics", tuple(sorted(diagnostics)))
        if self.availability == "ready" and diagnostics:
            object.__setattr__(self, "availability", "blocked")
        return self

    @computed_field
    @property
    def fingerprint(self) -> str:
        payload = self.model_dump(mode="json", exclude={"fingerprint"})
        return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()

    @property
    def total_demand(self) -> float:
        return sum(item.demand_value for item in self.points)

    @property
    def readiness(self) -> Literal["ready", "pending", "blocked"]:
        return self.availability

    @property
    def digest(self) -> str:
        return f"sha256:{self.fingerprint}"


def build_demand_snapshot(
    demand_ref: str,
    points: Iterable[FacilityDemandPoint],
    *,
    source_refs: Iterable[str] = (),
    source_binding: str = "",
    crs: str = "EPSG:4326",
    time_slice: str = "",
    version: str = "",
    declared_total_demand: float | None = None,
) -> DemandSnapshot:
    return DemandSnapshot(
        demand_ref=demand_ref,
        points=tuple(sorted(points, key=lambda item: item.demand_id)),
        source_refs=tuple(sorted({str(item) for item in source_refs if str(item)})),
        source_binding=source_binding,
        crs=crs,
        time_slice=time_slice,
        version=version,
        declared_total_demand=declared_total_demand,
        availability="ready" if source_binding and source_refs and version else "pending",
    )


__all__ = [
    "DemandSnapshot",
    "FacilityDemandPoint",
    "build_demand_snapshot",
]
