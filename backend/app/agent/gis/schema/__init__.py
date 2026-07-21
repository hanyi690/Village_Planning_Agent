"""GIS Agent schema subpackage — spatially-aware Pydantic models for PARSE Agent."""

from .parse_state import (
    # Spatial context models
    LanduseEntry,
    NaturalVillageAnchor,
    SpatialRelation,
    ConstraintSummary,
    SpatialContext,
    # Spatial operation models
    SpatialAnchor,
    SpatialOperation,
    # Spatial constraint models
    SpatialRule,
    SpatialConstraint,
    # Spatial planning intent models
    SpatialPreference,
    AdjacencyRules,
    ZoneTarget,
    FacilityTarget,
    AxisTarget,
    SpatialPlanningIntent,
    # Section classification
    SectionInfo,
    SectionClassificationResult,
    # PARSE Agent state
    ParseAgentState,
)

__all__ = [
    "LanduseEntry",
    "NaturalVillageAnchor",
    "SpatialRelation",
    "ConstraintSummary",
    "SpatialContext",
    "SpatialAnchor",
    "SpatialOperation",
    "SpatialRule",
    "SpatialConstraint",
    "SpatialPreference",
    "AdjacencyRules",
    "ZoneTarget",
    "FacilityTarget",
    "AxisTarget",
    "SpatialPlanningIntent",
    "SectionInfo",
    "SectionClassificationResult",
    "ParseAgentState",
]
