from __future__ import annotations

from typing import Any, Dict

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SpatialFeature(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    geometry: Dict[str, Any]
    bsm: str = Field(default="", alias="BSM")
    ysdm: str = Field(default="", alias="YSDM")
    layer_type: str = ""

    @field_validator("geometry")
    @classmethod
    def _validate_geometry_present(cls, v):
        if not v or "type" not in v:
            raise ValueError("geometry must be a valid GeoJSON geometry dict")
        return v

    @property
    def geometry_type(self) -> str:
        return self.geometry.get("type", "Unknown")


class PointFeature(SpatialFeature):
    @field_validator("geometry")
    @classmethod
    def _validate_point_geom(cls, v):
        if v.get("type") not in ("Point", "MultiPoint"):
            raise ValueError(f"PointFeature requires Point/MultiPoint, got {v.get('type')}")
        return v


class LineFeature(SpatialFeature):
    @field_validator("geometry")
    @classmethod
    def _validate_line_geom(cls, v):
        if v.get("type") not in ("LineString", "MultiLineString"):
            raise ValueError(f"LineFeature requires LineString/MultiLineString, got {v.get('type')}")
        return v


class PolygonFeature(SpatialFeature):
    @field_validator("geometry")
    @classmethod
    def _validate_polygon_geom(cls, v):
        if v.get("type") not in ("Polygon", "MultiPolygon"):
            raise ValueError(f"PolygonFeature requires Polygon/MultiPolygon, got {v.get('type')}")
        return v


class RasterDataset(BaseModel):
    model_config = ConfigDict(extra="allow")

    path: str = ""
    crs: str = "EPSG:4490"
    bounds: Any = None
    width: int = 0
    height: int = 0
    transform: Any = None
    band_count: int = 1
    dtype: str = "Float32"
    layer_type: str = ""


__all__ = [
    "SpatialFeature",
    "PointFeature",
    "LineFeature",
    "PolygonFeature",
    "RasterDataset",
]