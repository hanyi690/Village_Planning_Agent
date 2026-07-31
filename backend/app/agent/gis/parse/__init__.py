"""PARSE Agent subpackage - unified planning text parser.

Public API:
  parse / parse_async - deterministic rule-based parsing
  ParseResult - output container with SpatialPlanningIntent
"""

from .agent import parse, parse_async, ParseResult
from .state import (
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

__all__ = [
    # API
    "parse",
    "parse_async",
    "ParseResult",
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
]
