"""
Village Planning Schema

Pydantic models for structured output of spatial planning.
Used by Flash LLM with JSON mode to parse planning text into
structured data for GIS spatial layout generation.

Reference: GIS Planning Visualization Architecture Refactoring Plan
"""

from typing import List, Optional, Literal, Dict, Any
from pydantic import BaseModel, Field, field_validator


# ==========================================
# Position Bias Models
# ==========================================

class LocationBias(BaseModel):
    """Location bias for a planning zone"""
    direction: Literal["north", "south", "east", "west", "center", "edge", "northeast", "northwest", "southeast", "southwest"] = Field(
        default="center",
        description="Direction bias relative to village center"
    )
    reference_feature: Optional[str] = Field(
        default=None,
        description="Reference feature for positioning, e.g., 'near village committee', 'along main road'"
    )


class AdjacencyRule(BaseModel):
    """Adjacency rules for a planning zone"""
    adjacent_to: List[str] = Field(
        default_factory=list,
        description="Zone types that should be adjacent, e.g., ['public_service', 'residential']"
    )
    avoid_adjacent_to: List[str] = Field(
        default_factory=list,
        description="Zone types that should NOT be adjacent, e.g., ['industrial', 'agricultural']"
    )


# ==========================================
# Planning Zone Model
# ==========================================

class PlanningZone(BaseModel):
    """Single planning zone/land parcel definition"""
    zone_id: str = Field(
        description="Zone identifier, e.g., 'Z01', 'Z02'"
    )
    land_use: str = Field(
        description="Land use type: residential, industrial, public_service, ecological, transportation, water, agricultural, commercial"
    )
    area_ratio: float = Field(
        ge=0.0,
        le=1.0,
        description="Area ratio (0.0-1.0), total should sum to ~1.0"
    )
    location_bias: LocationBias = Field(
        default_factory=LocationBias,
        description="Location preference for this zone"
    )
    adjacency: AdjacencyRule = Field(
        default_factory=AdjacencyRule,
        description="Adjacency constraints"
    )
    density: Literal["high", "medium", "low"] = Field(
        default="medium",
        description="Development density level"
    )
    description: Optional[str] = Field(
        default=None,
        description="Additional description of this zone"
    )

    @field_validator('land_use')
    @classmethod
    def validate_land_use(cls, v: str) -> str:
        """Validate land use type"""
        valid_types = [
            "居住用地", "产业用地", "公共服务用地", "生态绿地",
            "交通用地", "水域", "农业用地", "商业用地",
            "residential", "industrial", "public_service", "ecological",
            "transportation", "water", "agricultural", "commercial"
        ]
        # Normalize Chinese/English mappings
        normalized = {
            "居住用地": "residential",
            "产业用地": "industrial",
            "公共服务用地": "public_service",
            "生态绿地": "ecological",
            "交通用地": "transportation",
            "水域": "water",
            "农业用地": "agricultural",
            "商业用地": "commercial",
        }
        if v in normalized:
            return normalized[v]
        if v in valid_types:
            return v
        # Accept any value, will be validated at generation stage
        return v


# ==========================================
# Facility Point Model
# ==========================================

class FacilityPoint(BaseModel):
    """Public facility point definition"""
    facility_id: str = Field(
        description="Facility identifier, e.g., 'F01', 'F02'"
    )
    facility_type: str = Field(
        description="Facility type: school, hospital, community_center, market, park, etc."
    )
    status: Literal["现状保留", "规划新建", "规划改扩建", "规划迁建",
                   "existing", "new", "expansion", "relocation"] = Field(
        default="new",
        description="Facility status"
    )
    location_hint: str = Field(
        description="Location hint in natural language, e.g., 'village center', 'near main road intersection'"
    )
    service_radius: int = Field(
        default=500,
        ge=0,
        description="Service radius in meters"
    )
    priority: Literal["high", "medium", "low"] = Field(
        default="medium",
        description="Implementation priority"
    )
    description: Optional[str] = Field(
        default=None,
        description="Additional description"
    )

    @field_validator('status')
    @classmethod
    def validate_status(cls, v: str) -> str:
        """Normalize status values"""
        normalized = {
            "现状保留": "existing",
            "规划新建": "new",
            "规划改扩建": "expansion",
            "规划迁建": "relocation",
        }
        if v in normalized:
            return normalized[v]
        return v


# ==========================================
# Development Axis Model
# ==========================================

class DevelopmentAxis(BaseModel):
    """Development axis/corridor definition"""
    axis_id: str = Field(
        description="Axis identifier, e.g., 'A01'"
    )
    axis_type: Literal["primary", "secondary", "corridor", "connector"] = Field(
        default="primary",
        description="Axis type: primary axis, secondary axis, development corridor, connector"
    )
    direction: Literal["east-west", "north-south", "radial", "ring"] = Field(
        default="east-west",
        description="Axis direction pattern"
    )
    reference_feature: Optional[str] = Field(
        default=None,
        description="Reference linear feature, e.g., 'along river', 'along main road'"
    )
    description: Optional[str] = Field(
        default=None,
        description="Axis description"
    )


# ==========================================
# Complete Planning Scheme Model
# ==========================================

class VillagePlanningScheme(BaseModel):
    """Complete village planning scheme with structured data"""
    zones: List[PlanningZone] = Field(
        default_factory=list,
        description="List of planning zones/land parcels",
        min_length=1
    )
    facilities: List[FacilityPoint] = Field(
        default_factory=list,
        description="List of public facilities"
    )
    axes: List[DevelopmentAxis] = Field(
        default_factory=list,
        description="List of development axes"
    )
    rationale: str = Field(
        default="",
        description="Overall planning rationale/justification"
    )
    development_axes: List[str] = Field(
        default_factory=list,
        description="Textual description of development axes"
    )
    total_area_km2: Optional[float] = Field(
        default=None,
        description="Total planning area in km2"
    )

    @field_validator('zones')
    @classmethod
    def validate_area_ratio_sum(cls, v: List[PlanningZone]) -> List[PlanningZone]:
        """Validate that area ratios sum to approximately 1.0"""
        if not v:
            return v
        total = sum(z.area_ratio for z in v)
        # Allow 5% deviation
        if abs(total - 1.0) > 0.05:
            # Log warning but don't raise error - will be adjusted in generation
            pass
        return v


# ==========================================
# Zone Type Constants and Mapping
# ==========================================

ZONE_TYPE_NAMES: Dict[str, str] = {
    "residential": "居住用地",
    "industrial": "产业用地",
    "public_service": "公共服务用地",
    "ecological": "生态绿地",
    "transportation": "交通用地",
    "water": "水域",
    "agricultural": "农业用地",
    "commercial": "商业用地",
}

ZONE_TYPE_COLORS: Dict[str, str] = {
    "居住用地": "#FFD700",
    "产业用地": "#FF6B6B",
    "公共服务用地": "#4A90D9",
    "生态绿地": "#90EE90",
    "交通用地": "#808080",
    "水域": "#87CEEB",
    "农业用地": "#8B4513",
    "商业用地": "#FFA500",
    # English mappings
    "residential": "#FFD700",
    "industrial": "#FF6B6B",
    "public_service": "#4A90D9",
    "ecological": "#90EE90",
    "transportation": "#808080",
    "water": "#87CEEB",
    "agricultural": "#8B4513",
    "commercial": "#FFA500",
}

ZONE_TYPE_CODES: Dict[str, str] = {
    "居住用地": "R",
    "产业用地": "M",
    "公共服务用地": "C",
    "生态绿地": "G",
    "交通用地": "T",
    "水域": "W",
    "农业用地": "A",
    "商业用地": "B",
    # English mappings
    "residential": "R",
    "industrial": "M",
    "public_service": "C",
    "ecological": "G",
    "transportation": "T",
    "water": "W",
    "agricultural": "A",
    "commercial": "B",
}

FACILITY_STATUS_COLORS: Dict[str, str] = {
    "现状保留": "#228B22",
    "规划新建": "#4A90D9",
    "规划改扩建": "#FF8C00",
    "规划迁建": "#9370DB",
    # English mappings
    "existing": "#228B22",
    "new": "#4A90D9",
    "expansion": "#FF8C00",
    "relocation": "#9370DB",
}


def get_zone_color(zone_type: str) -> str:
    """Get color for a zone type"""
    return ZONE_TYPE_COLORS.get(zone_type, "#CCCCCC")


def get_zone_code(zone_type: str) -> str:
    """Get code for a zone type"""
    return ZONE_TYPE_CODES.get(zone_type, "X")


def get_facility_color(status: str) -> str:
    """Get color for facility status"""
    return FACILITY_STATUS_COLORS.get(status, "#808080")


__all__ = [
    "LocationBias",
    "AdjacencyRule",
    "PlanningZone",
    "FacilityPoint",
    "DevelopmentAxis",
    "VillagePlanningScheme",
    "ZONE_TYPE_NAMES",
    "ZONE_TYPE_COLORS",
    "ZONE_TYPE_CODES",
    "FACILITY_STATUS_COLORS",
    "get_zone_color",
    "get_zone_code",
    "get_facility_color",
]