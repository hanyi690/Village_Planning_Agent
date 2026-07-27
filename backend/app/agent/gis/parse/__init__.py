"""PARSE Agent subpackage — spatially-aware planning text parsing.

Independent from LAYOUT Pipeline — communicates via state injection.

Architecture:
  classify_sections -> route_by_section -> extract_* -> validate_and_merge

Key design:
  - SpatialContext injected into PARSE (spatial relations, no raw geometry)
  - DictionaryCenter as single source of truth for encoding lookups
  - Strict Pydantic output schemas for reliable PARSE -> LAYOUT handoff
  - SpatialAnchor: dual-stage localization (PARSE pre-resolves, LAYOUT confirms)
"""

from .state import (
    # Spatial context models
    AdjacencyRules,
    AxisTarget,
    ComplianceCheck,
    ConstraintSummary,
    ContextBlock,
    FacilityTarget,
    LanduseEntry,
    ResidentialClusterAnchor,
    ParseAgentState,
    SectionClassificationResult,
    SectionInfo,
    SpatialAnchor,
    SpatialConstraint,
    SpatialOperation,
    SpatialPlanningIntent,
    SpatialPreference,
    SpatialRelation,
    SpatialRule,
    ZoneTarget,
)
from .agent import build_parse_agent_graph

__all__ = [
    # Schema classes
    "AdjacencyRules",
    "AxisTarget",
    "ComplianceCheck",
    "ConstraintSummary",
    "ContextBlock",
    "FacilityTarget",
    "LanduseEntry",
    "ResidentialClusterAnchor",
    "ParseAgentState",
    "SectionClassificationResult",
    "SectionInfo",
    "SpatialAnchor",
    "SpatialConstraint",
    "SpatialOperation",
    "SpatialPlanningIntent",
    "SpatialPreference",
    "SpatialRelation",
    "SpatialRule",
    "ZoneTarget",
    # Agent
    "build_parse_agent_graph",
]
