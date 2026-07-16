"""PARSE Agent state and output schemas.

Semi-structured ReAct subgraph for village planning text parsing.
Independent from LAYOUT Pipeline — communicates via state injection.

Architecture:
  classify_sections -> route_by_section -> extract_* -> validate_and_merge

Key design:
  - GIS data summary injected into PARSE (statistics only, no geometry)
  - DictionaryCenter as single source of truth for encoding lookups
  - Strict Pydantic output schemas for reliable PARSE -> LAYOUT handoff
  - Not backward-compatible with legacy ParseAgentState TypedDict
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


# ── GIS Summary (injected into PARSE, statistics only) ──────────────


class GISSummary(BaseModel):
    """GIS data summary for PARSE Agent context injection.

    Contains only statistics — no geometry data.
    Lets LLM reference current land use, natural villages, etc. during extraction.
    """

    parcel_count: int = 0
    current_landuse_stats: Dict[str, float] = Field(default_factory=dict)
    natural_villages: List[str] = Field(default_factory=list)
    planning_zone_stats: Dict[str, float] = Field(default_factory=dict)
    total_area_ha: float = 0.0
    construction_boundary_ha: float = 0.0


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


# ── Operation output schema ─────────────────────────────────────────


class OperationItem(BaseModel):
    """Structured representation of a 5-type atomic operation.

    Extracted from planning text (projects, land adjustments, etc.)
    """

    action: Literal["create", "split", "merge", "modify", "reclassify"]

    # ── Common fields ──
    source_text: str = ""
    confidence: float = 1.0
    needs_confirmation: bool = True

    # ── create parameters ──
    project_name: Optional[str] = None
    location_desc: Optional[str] = None
    area_sqm: Optional[float] = None
    land_use_name: Optional[str] = None
    land_use_code: Optional[str] = None

    # ── split parameters ──
    source_bsm: Optional[str] = None
    split_ratio: Optional[float] = None

    # ── merge parameters ──
    source_bsms: Optional[List[str]] = None

    # ── modify/reclassify parameters ──
    field_changes: Optional[Dict[str, Any]] = None
    new_qmdlbm: Optional[str] = None

    # ── Metadata ──
    article_ref: str = ""
    natural_village: str = ""


# ── Constraint output schema ────────────────────────────────────────


class ConstraintItem(BaseModel):
    """Structured representation of a planning constraint.

    Extracted from regulations, protection rules, etc.
    """

    type: Literal[
        "area_constraint",
        "spatial_constraint",
        "building_constraint",
        "use_constraint",
        "boundary_constraint",
    ]
    source_text: str = ""
    article_ref: str = ""

    # ── Area constraint ──
    land_use: Optional[str] = None
    target_area_ha: Optional[float] = None
    operator: Optional[Literal["<=", ">=", "=="]] = None

    # ── Spatial constraint ──
    zone_type: Optional[str] = None
    rule: Optional[str] = None

    # ── Building constraint ──
    max_area_sqm: Optional[float] = None
    max_height_m: Optional[float] = None
    max_floors: Optional[int] = None
    setback_m: Optional[float] = None

    # ── Priority ──
    priority: Literal["mandatory", "recommended", "aspirational"] = "mandatory"


# ── Intent output schema ────────────────────────────────────────────


class PlanningIntent(BaseModel):
    """High-level planning intent (zone targets, facilities, axes).

    Consumed by LAYOUT Pipeline for spatial generation.
    """

    village_name: str = ""
    planning_period: str = ""

    # ── Zone targets ──
    zone_targets: Dict[str, float] = Field(default_factory=dict)

    # ── Facility requirements ──
    facilities: List[Dict[str, Any]] = Field(default_factory=list)

    # ── Development axes ──
    development_axes: List[Dict[str, Any]] = Field(default_factory=list)

    # ── Overall constraints ──
    total_area_ha: Optional[float] = None
    construction_area_ha: Optional[float] = None
    farmland_area_ha: Optional[float] = None
    ecological_area_ha: Optional[float] = None

    # ── Population ──
    population: Optional[int] = None


# ── PARSE Agent state ───────────────────────────────────────────────


class ParseAgentState(BaseModel):
    """PARSE Agent internal state (independent from LAYOUT Pipeline).

    Not backward-compatible with legacy ParseAgentState TypedDict.
    """

    # ── Input ──
    planning_text: str = ""
    village_name: str = ""
    gis_data_summary: GISSummary = Field(default_factory=GISSummary)

    # ── Classification result ──
    section_map: List[SectionInfo] = Field(default_factory=list)
    parse_strategy: Literal["full", "incremental", "section_only"] = "full"

    # ── Extraction results (intermediate) ──
    raw_operations: List[Dict[str, Any]] = Field(default_factory=list)
    raw_constraints: List[Dict[str, Any]] = Field(default_factory=list)
    raw_targets: Dict[str, Any] = Field(default_factory=dict)
    raw_tables: Dict[str, Any] = Field(default_factory=dict)

    # ── Validation results ──
    validation_errors: List[str] = Field(default_factory=list)
    parse_round: int = 0
    is_valid: bool = False

    # ── Final output (consumed by LAYOUT Pipeline) ──
    operation_sequence: List[OperationItem] = Field(default_factory=list)
    constraint_set: List[ConstraintItem] = Field(default_factory=list)
    intent_json: Dict[str, Any] = Field(default_factory=dict)

    # ── Messages (LangGraph accumulated) ──
    messages: List[Any] = Field(default_factory=list)


__all__ = [
    "GISSummary",
    "SectionInfo",
    "OperationItem",
    "ConstraintItem",
    "PlanningIntent",
    "ParseAgentState",
]
