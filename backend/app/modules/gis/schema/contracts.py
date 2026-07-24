"""Spatial data contracts — Pydantic models for intent + pipeline output.

Single source of truth for all data contract models crossing tool/agent boundaries.
Merges former intent.py (spatial intent) and pipeline.py (tool output schemas).

Produced by: LLM structured_output, pipeline tools
Consumed by: ZoneGenerator, FacilityPlacer, AxisBuilder, allocate/generate tools
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Literal, Optional, Tuple

from pydantic import BaseModel, Field


# ============================================================
# Spatial intent models
# ============================================================


class Direction(str, Enum):
    """Spatial direction qualifier for zone/facility placement."""

    CENTER = "center"
    NORTH = "north"
    SOUTH = "south"
    EAST = "east"
    WEST = "west"
    NORTHEAST = "northeast"
    NORTHWEST = "northwest"
    SOUTHEAST = "southeast"
    SOUTHWEST = "southwest"
    PERIPHERY = "periphery"
    EAST_WEST = "east-west"
    NORTH_SOUTH = "north-south"


class Density(str, Enum):
    """Development density qualifier."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ZoneIntent(BaseModel):
    """Declarative intent for a functional zone."""

    zone_id: str = ""
    land_use: str = ""
    dlbm: str = ""
    dlbm_aliases: List[str] = Field(default_factory=list)
    area_ratio: float = Field(default=0.0, ge=0.0, le=1.0)
    direction: Direction = Direction.CENTER
    reference_feature: str = ""
    adjacent_to: List[str] = Field(default_factory=list)
    avoid_adjacent_to: List[str] = Field(default_factory=list)
    density: Density = Density.MEDIUM
    preserve_existing: bool = True


class FacilityIntent(BaseModel):
    """Declarative intent for a facility point placement."""

    facility_id: str = ""
    facility_type: str = ""
    target_zone: str = ""
    location_hint: str = ""
    status: str = "existing"


class AxisIntent(BaseModel):
    """Declarative intent for a development axis."""

    axis_id: str = ""
    axis_type: str = ""
    direction: Direction = Direction.CENTER
    connects: List[str] = Field(default_factory=list)
    label: str = ""


class ConstraintIntent(BaseModel):
    """Declarative spatial constraint for layout generation."""

    constraint_id: str = ""
    constraint_type: str = ""
    geometry_ref: str = ""
    strict: bool = True


class UnifiedSpatialIntent(BaseModel):
    """Complete spatial intent — single source of truth for layout content."""

    zones: List[ZoneIntent] = Field(default_factory=list)
    facilities: List[FacilityIntent] = Field(default_factory=list)
    axes: List[AxisIntent] = Field(default_factory=list)
    constraints: List[ConstraintIntent] = Field(default_factory=list)
    conflicts_resolved: Optional[Any] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @property
    def total_area_ratio(self) -> float:
        return sum(z.area_ratio for z in self.zones)

    def get_zone_by_id(self, zone_id: str) -> Optional[ZoneIntent]:
        for z in self.zones:
            if z.zone_id == zone_id:
                return z
        return None

    def get_zone_by_land_use(self, land_use: str) -> List[ZoneIntent]:
        return [z for z in self.zones if z.land_use == land_use]


# ============================================================
# Pipeline output models
# ============================================================


class ConflictItem(BaseModel):
    """Single conflict detected across dimensions."""

    conflict_id: str = ""
    conflict_type: Literal["metric", "constraint", "spatial"] = "metric"
    description: str = ""
    severity: Literal["low", "medium", "high"] = "medium"
    source_a: str = ""
    source_b: str = ""
    resolution_suggestion: str = ""


class ConflictReport(BaseModel):
    """Output of detect_conflicts tool."""

    conflicts: List[ConflictItem] = Field(default_factory=list)
    total_count: int = 0
    by_type: Dict[str, int] = Field(default_factory=dict)
    severity: Literal["none", "low", "medium", "high"] = "none"


class ViolationItem(BaseModel):
    """Single validation violation."""

    check_name: str = ""
    description: str = ""
    actual_value: Any = None
    expected_value: Any = None
    fix_suggestion: str = ""


class ValidationReport(BaseModel):
    """Output of validate_layout — Worker-Evaluator pattern gate."""

    passed: bool = False
    violations: List[ViolationItem] = Field(default_factory=list)
    checks_total: int = 8
    checks_passed: int = 0
    retry_suggestions: List[str] = Field(default_factory=list)


class AllocationResult(BaseModel):
    """Output of allocate_zones — MIP or greedy allocation result."""

    allocated_geojson: Dict[str, Any] = Field(default_factory=dict)
    allocation_summary: Dict[str, Any] = Field(default_factory=dict)
    mode: Literal["mip", "greedy"] = "mip"
    elapsed_s: float = 0.0
    succeeded: bool = False
    error_message: str = ""


class ExportResult(BaseModel):
    """Output of export_gdb — 12-layer GeoPackage + land balance."""

    layers_exported: List[str] = Field(default_factory=list)
    output_dir: str = ""
    land_balance: Dict[str, Any] = Field(default_factory=dict)
    total_layers: int = 0
    succeeded: bool = False
    warnings: List[str] = Field(default_factory=list)


# ============================================================
# Spatial Context (computed from GIS data → LLM context injection)
# ============================================================


class LanduseEntry(BaseModel):
    """Single land-use category entry in spatial context.

    dlbm 字段的编码体系取决于数据来源:
      - 现状层 (current/landuse.geojson): appendix5 编码
      - 规划层 (planned/landuse.geojson DLBM列): tugui 编码
    """

    dlbm: str = ""
    name: str = ""
    count: int = 0
    area_ha: float = 0.0
    zone_type: str = ""
    planning_zone: str = ""


class NaturalVillageAnchor(BaseModel):
    """Natural village spatial anchor — PARSE uses this to resolve location_desc.

    Computed from landuse GeoJSON by clustering residential parcels
    and matching place_aliases.yaml.
    """

    name: str = ""
    center: Tuple[float, float] = (0.0, 0.0)
    parcel_ids: List[str] = Field(default_factory=list)
    dominant_landuse: str = ""
    adjacent_to: List[str] = Field(default_factory=list)


class SpatialRelation(BaseModel):
    """Spatial relation triple computed from GIS geometry.

    Subjects and objects are natural village names, land-use zones,
    or infrastructure features.
    """

    subject: str = ""
    relation: Literal[
        "east_of", "west_of", "north_of", "south_of",
        "adjacent_to", "contains", "contained_by",
        "near", "along", "between",
    ] = "adjacent_to"
    object: str = ""
    confidence: float = 1.0
    source: Literal[
        "geometry_computed", "alias_lookup", "llm_inferred",
    ] = "geometry_computed"


class ConstraintSummary(BaseModel):
    """Spatial summary of protection zones — PARSE uses this to structure constraints."""

    zone_type: str = ""
    rule: str = ""
    area_ha: Optional[float] = None
    geometry_type: Optional[str] = None
    overlaps_with: List[str] = Field(default_factory=list)


class FacilityAnchor(BaseModel):
    """Facility spatial anchor — precise location from annotation.geojson.

    Unlike NaturalVillageAnchor (clustered from residential parcels), this comes
    directly from annotation.geojson's 现状设施点 features, which carry exact
    coordinates and a typed facility classification.
    PARSE uses this to ground facility location_hints instead of fuzzy gazetteer.
    """

    name: str = ""                       # 注记文本, e.g. "村委会", "小学", "祠堂"
    facility_type: str = ""              # mapped type: "公共服务", "教育", "文化", "体育"
    category: str = ""                   # "现状设施点" / "规划设施点"
    center: Tuple[float, float] = (0.0, 0.0)


class SpatialContext(BaseModel):
    """Spatially-aware GIS context for PARSE Agent.

    Derived from GISDataBundle by compute_spatial_context().
    Compact representation: ~2KB for 660 parcels (vs ~5MB raw GeoJSON).

    Not injected: raw geometry coordinates (too large for LLM context).
    Injected: spatial relations + anchors + constraint summaries.
    """

    parcel_count: int = 0
    total_area_ha: float = 0.0
    construction_boundary_ha: float = 0.0

    landuse_distribution: List[LanduseEntry] = Field(default_factory=list)
    village_center: Optional[Tuple[float, float]] = None
    natural_villages: List[NaturalVillageAnchor] = Field(default_factory=list)
    spatial_relations: List[SpatialRelation] = Field(default_factory=list)
    constraint_summary: List[ConstraintSummary] = Field(default_factory=list)
    zone_adjacency: Dict[str, List[str]] = Field(default_factory=dict)

    # Precise anchors from annotation.geojson (exact coordinates, not clustered)
    facility_anchors: List[FacilityAnchor] = Field(default_factory=list)
    annotation_villages: List[NaturalVillageAnchor] = Field(default_factory=list)

    # Terrain profile (P2 reserved — from DEM analysis, None when no DEM data)
    terrain_profile: Optional["TerrainProfile"] = None


class TerrainProfile(BaseModel):
    """Terrain analysis summary — compact digest for LLM spatial reasoning.

    Populated from TerrainAnalysisResult when DEM data is available.
    Currently reserved (P2) — set to None when no DEM data exists.
    """

    slope_area_pct: Dict[str, float] = Field(default_factory=dict)
    # {"0-6": 25.3, "6-15": 40.1, "15-25": 28.5, ">25": 6.1}

    aspect_area_pct: Dict[str, float] = Field(default_factory=dict)
    # {"N": 12.5, "S": 18.2, ...}

    suitability_area_pct: Dict[str, float] = Field(default_factory=dict)
    # {"suitable": 30.0, "moderate": 35.0, "marginal": 25.0, "unsuitable": 10.0}


__all__ = [
    "Direction",
    "Density",
    "ZoneIntent",
    "FacilityIntent",
    "AxisIntent",
    "ConstraintIntent",
    "UnifiedSpatialIntent",
    "ConflictItem",
    "ConflictReport",
    "ViolationItem",
    "ValidationReport",
    "AllocationResult",
    "ExportResult",
    # Spatial context (GIS → Agent contract)
    "LanduseEntry",
    "NaturalVillageAnchor",
    "FacilityAnchor",
    "SpatialRelation",
    "ConstraintSummary",
    "SpatialContext",
    "TerrainProfile",
]
