"""Canonical GIS data models — the single normative representation for all GIS data.

All data entering the agent pipeline MUST be normalized to these Pydantic models.
Providers are responsible for CRS normalization (→WGS84) and type coercion.
Tools consume these models exclusively — no raw dicts pass between modules.

CRS Policy: All coordinates in WGS84 (EPSG:4326). Metric operations use
crs_engine.get_metric_crs() for on-demand CGCS2000 projection.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


class CRS(str, Enum):
    """Supported coordinate reference systems."""
    WGS84 = "EPSG:4326"
    CGCS2000 = "EPSG:4490"
    GCJ02 = "GCJ02"


class BBox(BaseModel):
    """Canonical bounding box — always WGS84 (EPSG:4326).

    Order: (west, south, east, north) matching OSMnx 2.x bbox convention.
    """

    west: float
    south: float
    east: float
    north: float
    crs: str = Field(default="EPSG:4326", frozen=True)

    @property
    def as_tuple(self) -> tuple[float, float, float, float]:
        return (self.west, self.south, self.east, self.north)

    @property
    def center_lon(self) -> float:
        return (self.west + self.east) / 2.0

    @property
    def center_lat(self) -> float:
        return (self.south + self.north) / 2.0

    def is_valid(self) -> bool:
        return (
            -180.0 <= self.west <= 180.0
            and -180.0 <= self.east <= 180.0
            and -90.0 <= self.south <= 90.0
            and -90.0 <= self.north <= 90.0
            and self.west < self.east
            and self.south < self.north
        )


class GeoFeature(BaseModel):
    """Canonical geographic feature — GeoJSON geometry + typed properties.

    All coordinates MUST be in WGS84 (EPSG:4326).
    """

    geometry: Dict[str, Any]  # GeoJSON geometry dict: {"type": "...", "coordinates": [...]}
    properties: Dict[str, Any] = Field(default_factory=dict)
    bbox: Optional[BBox] = None
    source_provider: str = ""  # "tianditu" | "osm" | "amap"

    @field_validator("geometry")
    @classmethod
    def _check_geojson_type(cls, v: Dict[str, Any]) -> Dict[str, Any]:
        if "type" not in v:
            raise ValueError("geometry must have 'type' key (GeoJSON)")
        if "coordinates" not in v:
            raise ValueError("geometry must have 'coordinates' key (GeoJSON)")
        return v

    @property
    def geometry_type(self) -> str:
        return self.geometry.get("type", "Unknown")

    @property
    def is_empty(self) -> bool:
        coords = self.geometry.get("coordinates", [])
        return len(coords) == 0

class ProviderLandParcel(GeoFeature):
    """External data provider parcel — raw geometry + unchecked DLBM.

    Produced by Tianditu/OSM/Amap adapters. Contains GeoFeature metadata
    (properties, source_provider, bbox) and basic DLBM-derived fields.

    This is NOT the internal pipeline type. To use in the pipeline, convert
    via ingestion.provider_to_parcel() which validates encodings and returns
    a CurrentLandUseParcel or PlannedLandUseParcel with explicit _system tags.
    """

    dlbm: str = ""
    area_ha: float = 0.0
    area_sqm: float = 0.0
    zone_type: str = ""
    planning_zone: str = ""
    primary_zone: str = ""


class GISMetadata(BaseModel):
    """Data provenance and quality metadata for a GISDataBundle."""

    village_name: str = ""
    bbox_wgs84: Optional[BBox] = None
    fetched_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    provider_sources: List[str] = Field(default_factory=list)
    crs_warnings: List[str] = Field(default_factory=list)
    parcel_count: int = 0
    road_count: int = 0
    water_count: int = 0


class GISDataBundle(BaseModel):
    """Complete GIS data collection for a village — the normative data container.

    This is the SINGLE object that flows through the entire pipeline.
    Created by GISDataOrchestrator, consumed by all downstream tools.

    landuse entries are BaseLandUseParcel (or subclasses) from ingestion.py.
    Forward reference used to avoid circular import with ingestion.
    """

    boundary: Optional[GeoFeature] = None
    landuse: List[Any] = Field(default_factory=list)  # List[BaseLandUseParcel]
    roads: List[GeoFeature] = Field(default_factory=list)
    water_bodies: List[GeoFeature] = Field(default_factory=list)
    annotations: List[GeoFeature] = Field(default_factory=list)
    dem: Optional[Any] = None
    metadata: GISMetadata = Field(default_factory=GISMetadata)
    standard_version: str = ""

    @property
    def total_area_ha(self) -> float:
        return sum(getattr(p, 'area_ha', 0.0) for p in self.landuse)

    @property
    def parcel_count(self) -> int:
        return len(self.landuse)

    def get_parcels_by_dlbm(self, dlbm: str) -> List[Any]:
        return [p for p in self.landuse if getattr(p, 'dlbm', '') == dlbm]

    def get_parcels_by_zone(self, zone_type: str) -> List[Any]:
        return [p for p in self.landuse if getattr(p, 'zone_type', '') == zone_type]

    def is_complete(self) -> bool:
        """Check minimum data requirements: boundary + landuse."""
        return self.boundary is not None and len(self.landuse) > 0


__all__ = [
    "CRS",
    "BBox",
    "GeoFeature",
    "ProviderLandParcel",
    "GISMetadata",
    "GISDataBundle",
]
