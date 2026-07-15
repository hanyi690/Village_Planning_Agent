"""GIS canonical data models — single source of truth for all GIS data structures.

All models use Pydantic BaseModel for runtime validation and type safety.
Providers normalize to these models, tools consume them, agent state holds them.
"""

from .canonical import (
    BBox,
    CRS,
    GeoFeature,
    LandUseParcel,
    GISDataBundle,
    GISMetadata,
)
from .intent import (
    Direction,
    Density,
    ZoneIntent,
    FacilityIntent,
    AxisIntent,
    ConstraintIntent,
    UnifiedSpatialIntent,
)
from .pipeline import (
    ConflictItem,
    ConflictReport,
    ViolationItem,
    ValidationReport,
    AllocationResult,
    ExportResult,
)
from .encoding_registry import EncodingRegistry, get_encoding_registry
from .output_profile import OutputProfile, LayerSpec, FieldSpec, get_output_profile

__all__ = [
    # Canonical data models
    "BBox",
    "CRS",
    "GeoFeature",
    "LandUseParcel",
    "GISDataBundle",
    "GISMetadata",
    # Intent models
    "Direction",
    "Density",
    "ZoneIntent",
    "FacilityIntent",
    "AxisIntent",
    "ConstraintIntent",
    "UnifiedSpatialIntent",
    # Pipeline output models
    "ConflictItem",
    "ConflictReport",
    "ViolationItem",
    "ValidationReport",
    "AllocationResult",
    "ExportResult",
    # Encoding registry
    "EncodingRegistry",
    "get_encoding_registry",
    # Output profile
    "OutputProfile",
    "LayerSpec",
    "FieldSpec",
    "get_output_profile",
]
