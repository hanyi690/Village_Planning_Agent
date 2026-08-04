"""GIS Agent state — unified Pydantic BaseModel following LangGraph best practices.

Migrated from agent/gis/state.py per docs/architecture/agent-graph.md §5.

Architecture:
  - GISPipelineInput: API-layer input (session, village, planning text)
  - GISPipelineOutput: API-layer output (export result, render result)
  - GISPipelineState: internal pipeline state (all intermediate data)

This replaces the previous 4-TypedDict design (GISAgentState, ParseAgentState,
LayoutAgentState, LayoutPipelineState) with a single Pydantic hierarchy.

References:
  [1] LangGraph: Multiple State Schemas (input_schema/output_schema/overall)
  [2] LangGraph: Pydantic BaseModel for runtime validation
  [3] LangGraph: ToolRuntime for typed tool state access
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field
from langchain_core.messages import BaseMessage


# ── Input schema — API layer provides these fields ──────────────────


class GISPipelineInput(BaseModel):
    """Fields the API caller must provide to invoke the pipeline."""

    session_id: str = ""
    village_name: str = ""
    planning_text: str = ""           # markdown planning report text (gen path)
    l3_reports: Dict[str, Any] = Field(default_factory=dict)  # L3 report data (plan path)
    reports: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    gis_data: Dict[str, Any] = Field(default_factory=dict)
    gis_bundle: Optional[Any] = None
    intent: Any = None                # v4: EXPLORE->Binder->format external intent
    intent_json: Any = None
    explore_instructions: Dict[str, Any] = Field(default_factory=dict)
    report_summary_index: Dict[str, Any] = Field(default_factory=dict)
    dimension_summaries: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ── Output schema — fields exposed to the API caller ─────────────────


class GISPipelineOutput(BaseModel):
    """Fields the pipeline returns to the frontend after completion."""

    session_id: str = ""
    village_name: str = ""
    layout_configs: List[Dict[str, Any]] = Field(default_factory=list)
    export_result: Dict[str, Any] = Field(default_factory=dict)
    render_result: List[Dict[str, Any]] = Field(default_factory=list)
    render_artifact: Dict[str, Any] = Field(default_factory=dict)
    validation_result: Dict[str, Any] = Field(default_factory=dict)
    validation_passed: bool = False
    validation_round: int = 0
    execution_errors: List[Dict[str, Any]] = Field(default_factory=list)
    conflict_result: Dict[str, Any] = Field(default_factory=dict)
    completed_at: Optional[datetime] = None


# ── Overall state — internal pipeline state, not exposed externally ──


class GISPipelineState(BaseModel):
    """Complete internal state of the GIS layout pipeline.

    All nodes in the StateGraph read from and write to this model.
    Uses default_factory for mutable fields (Pydantic requirement).
    """

    # ── Identity ──
    session_id: str = ""
    village_name: str = ""

    # ── Input data ──
    reports: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    gis_data: Dict[str, Any] = Field(default_factory=dict)
    gis_bundle: Optional[Any] = None  # GISDataBundle — typed data container

    # ── Intent + PARSE Agent output ──
    # Runtime type is SpatialPlanningIntent / List[SpatialOperation] / List[SpatialConstraint].
    # Declared as Any to allow both typed Pydantic models and legacy dict access
    # while supporting Pydantic serialization. Downstream code should prefer
    # attribute access (intent.zone_targets) when the value is a typed model.
    intent: Any = None
    intent_json: Any = None
    operation_sequence: List[Any] = Field(default_factory=list)
    constraint_set: List[Any] = Field(default_factory=list)
    planning_intent: Any = None
    # P2: EXPLORE 桥接产出（grounding 空间定位指令 + 概要索引）
    explore_instructions: Dict[str, Any] = Field(default_factory=dict)
    report_summary_index: Dict[str, Any] = Field(default_factory=dict)
    dimension_summaries: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    spatial_context: Dict[str, Any] = Field(default_factory=dict)  # DEPRECATED — use context_blocks
    context_blocks: List[Dict[str, Any]] = Field(default_factory=list)
    facility_anchors: Optional[List[Dict[str, Any]]] = None  # Precise facility locations from annotations

    # ── Knowledge Graph ──
    kg_turtle: str = ""  # RDF Turtle serialization
    kg_constraints: List[Dict[str, Any]] = Field(default_factory=list)
    kg_adjacency_map: Dict[str, List[str]] = Field(default_factory=dict)  # parcel BSM -> adjacent BSMs
    kg_zone_restrictions: Dict[str, Any] = Field(default_factory=dict)  # zone_name -> restriction list
    # KG cache references (KGManager side-channel, state stores only references)
    kg_session_ref: str = ""  # session_id → KGManager._session_kgs
    kg_layer1_cache_key: str = ""  # cache key → KGManager._layer1_cache
    kg_version: int = 0  # query cache version for invalidation
    # Pre-computed query results (eliminate redundant SPARQL at downstream tools)
    kg_parcel_count_by_zone: List[Dict[str, Any]] = Field(default_factory=list)
    kg_protected_parcels: Dict[str, Any] = Field(default_factory=dict)
    # Phase 5: expanded KG query results for downstream consumption
    kg_protected_parcels_detail: List[Dict[str, Any]] = Field(default_factory=list)  # get_protected_parcels_detail
    kg_three_zones: List[Dict[str, Any]] = Field(default_factory=list)  # get_three_zones
    kg_three_lines: List[Dict[str, Any]] = Field(default_factory=list)  # get_three_lines
    kg_village_anchors: List[Dict[str, Any]] = Field(default_factory=list)  # get_village_anchors
    kg_vne_summary: List[Dict[str, Any]] = Field(default_factory=list)  # count_by_vne
    kg_count_by_planning_zone: List[Dict[str, Any]] = Field(default_factory=list)  # count_by_planning_zone

    # ── Allocation ──
    allocated_geojson: Dict[str, Any] = Field(default_factory=dict)
    allocation_summary: Dict[str, Any] = Field(default_factory=dict)

    # ── Layout generation ──
    layout_configs: List[Dict[str, Any]] = Field(default_factory=list)
    execution_errors: List[Dict[str, Any]] = Field(default_factory=list)
    conflict_result: Dict[str, Any] = Field(default_factory=dict)

    # ── Validation ──
    validation_result: Dict[str, Any] = Field(default_factory=dict)
    validation_round: int = 0
    constraint_adjustments: List[Dict[str, Any]] = Field(default_factory=list)  # Step 3 feedback

    # ── Export ──
    export_result: Dict[str, Any] = Field(default_factory=dict)

    # ── Render ──
    render_result: List[Dict[str, Any]] = Field(default_factory=list)
    render_artifact: Dict[str, Any] = Field(default_factory=dict)

    # ── Messages (LangGraph accumulated) ──
    messages: List[Any] = Field(default_factory=list)


__all__ = [
    "GISPipelineInput",
    "GISPipelineOutput",
    "GISPipelineState",
]
