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

from pydantic import BaseModel, Field


from app.modules.gis.schema.contracts import (
    ConstraintSummary,
    LanduseEntry,
    NaturalVillageAnchor,
    SpatialContext,
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


# ── Spatial Operation output schema ─────────────────────────────────


class SpatialAnchor(BaseModel):
    """Spatial anchor for an operation — PARSE pre-resolves from SpatialContext.

    Dual-stage localization:
      - PARSE: matches location_desc against SpatialContext.natural_villages
               -> pre-resolves candidate parcels + confidence
      - LAYOUT: resolve_place_name confirms or corrects the anchor

    Inspired by GeoPlanAgent's "localisation" step:
      text description -> spatial reference -> candidate parcels.
    """

    reference: str = ""
    offset: Optional[str] = None
    secondary_ref: Optional[str] = None
    secondary_offset: Optional[str] = None
    candidate_parcels: List[str] = Field(default_factory=list)
    confidence: float = 0.0
    resolution_status: Literal[
        "anchored",
        "partial",
        "unresolved",
    ] = "unresolved"


class ComplianceCheck(BaseModel):
    """Compliance pre-check result — filled by Python computation, not LLM.

    Based on spatial_context.constraint_summary for deterministic checks.
    """

    in_construction_boundary: bool = True
    not_farmland: bool = True
    not_ecological_redline: bool = True
    within_village_boundary: bool = True


class SpatialOperation(BaseModel):
    """Spatially-aware atomic operation — PARSE outputs with spatial anchor.

    Inspired by Spatial-Agent's GeoFlow Graph concept:
      each operation = concept node + transform operator + spatial anchor.

    Aligned with OUTPUT_ARCHITECTURE.md §8 OperationSequence spec:
      - target_parcels: BSM list for EXECUTE_OPERATIONS
      - confidence_level: "high"/"medium"/"low" (spec format)
      - affected_layers: output layers impacted by this operation
      - compliance: deterministic pre-check result
    """

    action: Literal["create", "split", "merge", "modify", "reclassify"]

    # Spatial anchor (replaces location_desc free text)
    spatial_anchor: Optional[SpatialAnchor] = None

    # Free text fallback (only when spatial_anchor resolution fails)
    location_desc: Optional[str] = None

    # Target parcels — BSM list for EXECUTE_OPERATIONS (spec §8.1 target_parcels)
    target_parcels: List[str] = Field(default_factory=list)

    # Common fields
    source_text: str = ""
    confidence: float = 1.0
    confidence_level: Literal["high", "medium", "low"] = "high"
    needs_confirmation: bool = True

    # create parameters
    project_name: Optional[str] = None
    area_sqm: Optional[float] = None
    land_use_name: Optional[str] = None
    land_use_code: Optional[str] = None  # GHYTBM 编码 (附录5规划用途编码)

    # split parameters
    source_bsm: Optional[str] = None
    split_ratio: Optional[float] = None

    # merge parameters
    source_bsms: Optional[List[str]] = None

    # modify/reclassify parameters
    field_changes: Optional[Dict[str, Any]] = None
    new_qmdlbm: Optional[str] = None  # 期末地类编码 (土规数据库标准，非附录5)

    # Affected output layers (spec §8.3 changelog affected_layers)
    affected_layers: List[str] = Field(default_factory=list)

    # Compliance pre-check result (Python computation, not LLM)
    compliance: Optional[ComplianceCheck] = None

    # Metadata
    article_ref: str = ""
    natural_village: str = ""


# ── Spatial Constraint output schema ────────────────────────────────


class SpatialRule(BaseModel):
    """Computable spatial rule — directly maps to Shapely/GeoPandas operations.

    Inspired by GeoAgents' spatial.intersects / spatial.nearby design:
      each rule = deterministic spatial operation + parameters.
    """

    operation: Literal[
        "no_overlap",
        "buffer_exclusion",
        "contained_by",
        "adjacent_to",
        "distance_within",
    ] = "no_overlap"
    subject: str = ""
    object: str = ""
    distance_m: Optional[float] = None


class SpatialConstraint(BaseModel):
    """Spatially-aware constraint — PARSE outputs directly mappable to spatial ops.

    Inspired by GeoAgents' spatial tool design:
      constraint = spatial operation + geometric parameters.
    """

    type: Literal[
        "area_constraint",
        "spatial_constraint",
        "building_constraint",
        "use_constraint",
        "boundary_constraint",
    ] = "spatial_constraint"
    source_text: str = ""
    article_ref: str = ""
    priority: Literal[
        "mandatory",
        "recommended",
        "aspirational",
    ] = "mandatory"

    # Area constraint
    land_use: Optional[str] = None
    target_area_ha: Optional[float] = None
    operator: Optional[Literal["<=", ">=", "=="]] = None

    # Spatial constraint (enhanced)
    zone_type: Optional[str] = None
    spatial_rule: Optional[SpatialRule] = None

    # Building constraint
    max_area_sqm: Optional[float] = None
    max_height_m: Optional[float] = None
    max_floors: Optional[int] = None
    setback_m: Optional[float] = None


# ── Spatial Planning Intent output schema ───────────────────────────


class SpatialPreference(BaseModel):
    """Zone spatial preference — from PARSE's understanding of planning text."""

    direction: Optional[str] = None
    reference: Optional[str] = None


class AdjacencyRules(BaseModel):
    """Zone adjacency rules — from PARSE's understanding of regulations."""

    prefer: List[str] = Field(default_factory=list)
    avoid: List[str] = Field(default_factory=list)


class ZoneTarget(BaseModel):
    """Zone target with spatial preference."""

    land_use: str = ""
    area_ratio: float = 0.0
    dlbm: Optional[str] = None
    spatial_preference: Optional[SpatialPreference] = None
    adjacency_rules: Optional[AdjacencyRules] = None
    density: Literal["high", "medium", "low"] = "medium"


class FacilityTarget(BaseModel):
    """Facility requirement with spatial anchoring."""

    type: str = ""
    status: Literal[
        "existing_preserve",
        "planned_new",
        "planned_expand",
        "planned_relocate",
    ] = "existing_preserve"
    location_hint: str = ""
    service_radius: Optional[int] = None
    anchor_village: Optional[str] = None


class AxisTarget(BaseModel):
    """Development axis with connectivity."""

    direction: str = ""
    reference_feature: str = ""
    connects: List[str] = Field(default_factory=list)


class SpatialPlanningIntent(BaseModel):
    """Spatially-aware planning intent — PARSE outputs with spatial arrangement preference.

    Borrows adjacency/location_bias fields already defined but unused in prompts.py.
    """

    village_name: str = ""
    planning_period: str = ""

    # Zone targets (enhanced)
    zone_targets: List[ZoneTarget] = Field(default_factory=list)

    # Facility requirements (enhanced)
    facilities: List[FacilityTarget] = Field(default_factory=list)

    # Development axes (enhanced)
    development_axes: List[AxisTarget] = Field(default_factory=list)

    # Area constraints (preserved)
    total_area_ha: Optional[float] = None
    construction_area_ha: Optional[float] = None
    farmland_area_ha: Optional[float] = None
    ecological_area_ha: Optional[float] = None

    # Population
    population: Optional[int] = None


# ── PARSE Agent state ───────────────────────────────────────────────


class ParseAgentState(BaseModel):
    """PARSE Agent internal state (independent from LAYOUT Pipeline).

    Spatially-aware: uses SpatialContext instead of GISSummary,
    SpatialOperation instead of OperationItem,
    SpatialConstraint instead of ConstraintItem.
    """

    # Input
    planning_text: str = ""
    village_name: str = ""
    spatial_context: SpatialContext = Field(default_factory=SpatialContext)

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
    "LanduseEntry",
    "NaturalVillageAnchor",
    "SpatialRelation",
    "ConstraintSummary",
    "SpatialContext",
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
