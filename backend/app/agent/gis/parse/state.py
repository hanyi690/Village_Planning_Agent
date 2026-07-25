"""PARSE Agent state and output schemas — Spatially-Aware PARSE.

Semi-structured ReAct subgraph for village planning text parsing.
Independent from LAYOUT Pipeline — communicates via state injection.

Architecture:
  classify_sections -> route_by_section -> extract_* -> validate_and_merge

Key design:
  - SpatialContext injected into PARSE (spatial relations, no raw geometry)
  - DictionaryCenter as single source of truth for encoding lookups
  - Strict Pydantic output schemas for reliable PARSE -> LAYOUT handoff
  - SpatialAnchor: dual-stage localization (PARSE pre-resolves, LAYOUT confirms)

Inspired by:
  - Spatial-Agent: GeoFlow Graph (concept transformation, not free text)
  - GeoAgents: spatial tools as first-class citizens (SpatialRule -> Shapely ops)
  - GeoWorkbench: compute_spatial_context() as explicit pipeline stage
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, computed_field


from app.modules.schema.contracts.context_contracts import (
    ConstraintSummary,
    ContextBlock,
    LanduseEntry,
    NaturalVillageAnchor,
    SpatialRelation,
)


# ── Section classification ──────────────────────────────────────────


class SectionInfo(BaseModel):
    """Document section classification result."""

    section_id: str = ""
    title: str = ""
    section_type: Literal[
        "preamble",
        "target",
        "regulation",
        "project_table",
        "land_use_table",
        "indicator_table",
        "heritage_table",
        "facility_table",
        "ecological_table",
        "spatial_layout",
        "protection",
        "infrastructure",
        "governance",
    ] = "preamble"
    content: str = ""
    has_table: bool = False


class SectionClassificationResult(BaseModel):
    """Structured output for classify_sections node."""

    sections: List[SectionInfo] = Field(default_factory=list)
    document_type: Literal[
        "village_plan",
        "special_plan",
        "implementation",
        "unknown",
    ] = "unknown"


# ── Spatial Operation / Constraint schemas ──────────────────────────
# Moved to app.modules.schema.contracts.parse_contracts — shared data
# contract between PARSE Agent and KG/EXECUTE. Imported here for backward
# compat and agent-internal use.

from app.modules.schema.contracts.parse_contracts import (
    SpatialAnchor,
    ComplianceCheck,
    SpatialOperation,
    SpatialRule,
    SpatialConstraint,
)


# ── Spatial Planning Intent output schema ───────────────────────────
# Moved to app.modules.schema.contracts.parse_contracts — shared data contract
# between PARSE Agent and KG/Tools. Imported here for backward compat.



# ── Spatial Planning Intent output schema ───────────────────────────
# Moved to app.modules.schema.parse_contracts — shared data contract
# between PARSE Agent and KG/Tools. Imported here for backward compat.

from app.modules.schema.contracts.parse_contracts import (
    SpatialPreference,
    AdjacencyRules,
    ZoneTarget,
    FacilityTarget,
    AxisTarget,
    PlanningIndicatorItem,
    PlanningIndicatorTable,
    ThreeZoneItem,
    ThreeLineItem,
    ThreeZonesThreeLines,
    SpatialPlanningIntent,
)


# ── PARSE Agent state ───────────────────────────────────────────────


class ParseAgentState(BaseModel):
    """PARSE Agent internal state (independent from LAYOUT Pipeline).

    Spatially-aware: uses ContextBlock list instead of SpatialContext,
    SpatialOperation instead of OperationItem,
    SpatialConstraint instead of ConstraintItem.
    """

    # Input
    planning_text: str = ""
    village_name: str = ""
    context_blocks: List[ContextBlock] = Field(default_factory=list)

    # Classification result
    section_map: List[SectionInfo] = Field(default_factory=list)
    parse_strategy: Literal["full", "incremental", "section_only"] = "full"

    # Extraction results (intermediate — typed, not raw dicts)
    raw_operations: List[SpatialOperation] = Field(default_factory=list)
    raw_constraints: List[SpatialConstraint] = Field(default_factory=list)
    raw_targets: SpatialPlanningIntent = Field(default_factory=SpatialPlanningIntent)
    raw_tables: Dict[str, Any] = Field(default_factory=dict)

    # Validation results
    validation_errors: List[str] = Field(default_factory=list)
    parse_round: int = 0
    is_valid: bool = False

    # Final output (consumed by LAYOUT Pipeline)
    operation_sequence: List[SpatialOperation] = Field(default_factory=list)
    constraint_set: List[SpatialConstraint] = Field(default_factory=list)
    planning_intent: SpatialPlanningIntent = Field(
        default_factory=SpatialPlanningIntent
    )

    # Draft texts from Phase A (think/explore nodes — Think-Then-Format pattern)
    draft_operations: str = ""
    draft_targets: str = ""

    # Per-extract-node mappings (separate keys avoid InvalidUpdateError
    # when explore_projects and explore_targets run in parallel)
    code_mappings_projects: Dict[str, str] = Field(default_factory=dict)
    place_mappings_projects: Dict[str, dict] = Field(default_factory=dict)
    code_mappings_targets: Dict[str, str] = Field(default_factory=dict)
    place_mappings_targets: Dict[str, dict] = Field(default_factory=dict)

    # Messages (LangGraph accumulated)
    messages: List[Any] = Field(default_factory=list)

    # Per-node LLM trace data (separate keys avoid InvalidUpdateError
    # when explore_projects and explore_targets run in parallel)
    llm_trace_projects: List[Dict[str, Any]] = Field(default_factory=list)
    llm_trace_targets: List[Dict[str, Any]] = Field(default_factory=list)


__all__ = [
    # Spatial context
    "ContextBlock",
    "LanduseEntry",
    "NaturalVillageAnchor",
    "SpatialRelation",
    "ConstraintSummary",
    # Section classification
    "SectionInfo",
    "SectionClassificationResult",
    # Spatial operation
    "SpatialAnchor",
    "ComplianceCheck",
    "SpatialOperation",
    # Spatial constraint
    "SpatialRule",
    "SpatialConstraint",
    # Spatial planning intent
    "SpatialPreference",
    "AdjacencyRules",
    "ZoneTarget",
    "FacilityTarget",
    "AxisTarget",
    "SpatialPlanningIntent",
    # PARSE Agent state
    "ParseAgentState",
]
