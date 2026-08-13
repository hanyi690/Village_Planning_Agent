"""Typed contracts for deterministic DEM-derived terrain evidence.

The contracts contain no raster arrays. They are small serializable artifacts
that can be cached, attached to a suitability surface, and independently
audited without reopening the source raster.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class TerrainEvidenceConfig(BaseModel):
    """Technical controls for bounded deterministic raster reads."""

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    band: int = Field(default=1, ge=1)
    all_touched: bool = False
    window_padding_pixels: int = Field(default=1, ge=1, le=8)
    max_window_cells: int = Field(default=4_000_000, ge=9)
    elevation_unit_scale_to_m: float = Field(default=1.0, gt=0.0)


class TerrainRasterMetadata(BaseModel):
    """Validated identity and georeferencing metadata for one DEM."""

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    source_path: str
    source_origin: Literal["planning_context", "catalog", "explicit_path"]
    source_sha256: str
    source_size_bytes: int = Field(ge=0)
    source_mtime_ns: int = Field(ge=0)
    crs: str = ""
    transform: tuple[float, float, float, float, float, float]
    bounds: tuple[float, float, float, float]
    width: int = Field(ge=0)
    height: int = Field(ge=0)
    band_count: int = Field(ge=0)
    dtype: str = ""
    nodata: float | None = None
    pixel_size_x: float = Field(ge=0.0)
    pixel_size_y: float = Field(ge=0.0)
    is_geographic: bool = False
    valid: bool = False
    diagnostics: tuple[str, ...] = ()


class TerrainStatistics(BaseModel):
    """Distribution summary over cells selected by a geometry mask."""

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    unit: str
    total_cell_count: int = Field(ge=0)
    valid_cell_count: int = Field(ge=0)
    valid_fraction: float = Field(ge=0.0, le=1.0)
    minimum: float | None = None
    maximum: float | None = None
    mean: float | None = None
    median: float | None = None
    p10: float | None = None
    p90: float | None = None
    standard_deviation: float | None = None


class TerrainEvidenceProvenance(BaseModel):
    """Audit trail for one geometry-window calculation."""

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    source_path: str
    source_origin: str
    source_sha256: str
    raster_crs: str
    geometry_crs: str
    geometry_sha256: str
    raster_transform: tuple[float, float, float, float, float, float]
    raster_nodata: float | None = None
    raster_band: int = Field(ge=1)
    window: tuple[int, int, int, int]
    horizontal_scale_method: Literal["projected_axis_units", "geodesic_cell_vectors"]
    horizontal_pixel_size_m: tuple[float, float]
    elevation_algorithm: str = "rasterio_window_geometry_mask"
    slope_algorithm: str = "numpy_gradient_rise_over_run_degrees"
    cache_key: str
    cache_hit: bool = False


class TerrainEvidence(BaseModel):
    """Elevation and slope evidence for one parcel or candidate geometry."""

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    evidence_id: str
    subject_id: str
    status: Literal[
        "ready",
        "invalid_raster",
        "invalid_geometry",
        "outside_raster",
        "window_too_large",
        "no_valid_cells",
    ]
    elevation: TerrainStatistics
    slope: TerrainStatistics
    relief_m: float | None = None
    diagnostics: tuple[str, ...] = ()
    provenance: TerrainEvidenceProvenance


class TerrainPointSample(BaseModel):
    """One explicit Rasterio sample with an optional local slope estimate."""

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    sample_id: str
    input_coordinate: tuple[float, float]
    raster_coordinate: tuple[float, float]
    row: int | None = None
    column: int | None = None
    elevation_m: float | None = None
    slope_degrees: float | None = None
    status: Literal["ready", "outside_raster", "nodata"]


class TerrainPointSampleSet(BaseModel):
    """Auditable batch returned by the explicit point-sampling interface."""

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    sample_set_id: str
    coordinate_crs: str
    samples: tuple[TerrainPointSample, ...]
    source_sha256: str
    cache_key: str
    cache_hit: bool = False


class TerrainSuitabilityPolicy(BaseModel):
    """Caller-owned thresholds; the raster engine never invents them."""

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    preferred_max_slope_degrees: float = Field(ge=0.0, le=90.0)
    hard_max_slope_degrees: float = Field(gt=0.0, le=90.0)
    minimum_valid_fraction: float = Field(ge=0.0, le=1.0)
    slope_statistic: Literal["mean", "p90", "maximum"] = "p90"
    minimum_elevation_m: float | None = None
    maximum_elevation_m: float | None = None
    maximum_relief_m: float | None = Field(default=None, gt=0.0)

    @model_validator(mode="after")
    def validate_ranges(self) -> "TerrainSuitabilityPolicy":
        if self.preferred_max_slope_degrees > self.hard_max_slope_degrees:
            raise ValueError("preferred slope cannot exceed hard maximum slope")
        if (
            self.minimum_elevation_m is not None
            and self.maximum_elevation_m is not None
            and self.minimum_elevation_m > self.maximum_elevation_m
        ):
            raise ValueError("minimum elevation cannot exceed maximum elevation")
        return self


class TerrainSuitabilityAssessment(BaseModel):
    """Deterministic terrain-only suitability contribution."""

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    evidence_id: str
    classification: Literal["preferred", "conditional", "unsuitable", "unknown"]
    score: float = Field(ge=0.0, le=1.0)
    hard_feasible: bool
    evaluated_slope_degrees: float | None = None
    reasons: tuple[str, ...] = ()
    policy: TerrainSuitabilityPolicy


__all__ = [
    "TerrainEvidence",
    "TerrainEvidenceConfig",
    "TerrainEvidenceProvenance",
    "TerrainPointSample",
    "TerrainPointSampleSet",
    "TerrainRasterMetadata",
    "TerrainStatistics",
    "TerrainSuitabilityAssessment",
    "TerrainSuitabilityPolicy",
]
