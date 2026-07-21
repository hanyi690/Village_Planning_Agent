"""GIS Agent state — unified Pydantic BaseModel following LangGraph best practices.

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
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ── Output schema — fields exposed to the API caller ─────────────────


class GISPipelineOutput(BaseModel):
    """Fields the pipeline returns to the frontend after completion."""

    session_id: str = ""
    village_name: str = ""
    layout_configs: List[Dict[str, Any]] = Field(default_factory=list)
    export_result: Dict[str, Any] = Field(default_factory=dict)
    render_result: List[Dict[str, Any]] = Field(default_factory=list)
    validation_passed: bool = False
    validation_round: int = 0
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
    gis_data: Dict[str, Optional[Dict[str, Any]]] = Field(default_factory=dict)

    # ── Intent (LLM output) ──
    intent: Dict[str, Any] = Field(default_factory=dict)
    intent_json: Dict[str, Any] = Field(default_factory=dict)

    # ── PARSE Agent output (spatially-aware) ──
    operation_sequence: List[Dict[str, Any]] = Field(default_factory=list)
    constraint_set: List[Dict[str, Any]] = Field(default_factory=list)
    planning_intent: Dict[str, Any] = Field(default_factory=dict)
    spatial_context: Dict[str, Any] = Field(default_factory=dict)

    # ── Knowledge Graph ──
    kg_turtle: str = ""  # RDF Turtle serialization
    kg_constraints: List[Dict[str, Any]] = Field(default_factory=list)

    # ── Allocation ──
    allocated_geojson: Dict[str, Any] = Field(default_factory=dict)
    allocation_summary: Dict[str, Any] = Field(default_factory=dict)

    # ── Layout generation ──
    layout_configs: List[Dict[str, Any]] = Field(default_factory=list)

    # ── Validation ──
    validation_result: Dict[str, Any] = Field(default_factory=dict)
    validation_round: int = 0

    # ── Export ──
    export_result: Dict[str, Any] = Field(default_factory=dict)

    # ── Render ──
    render_result: List[Dict[str, Any]] = Field(default_factory=list)

    # ── Messages (LangGraph accumulated) ──
    messages: List[Any] = Field(default_factory=list)


# ── Legacy type aliases — for backward compatibility ─────────────────


# Deprecated: these TypedDict aliases exist only for backward compatibility.
# New code should use GISPipelineState (Pydantic BaseModel).
# Remove after all callers have migrated.

from typing import TypedDict as _TypedDict
from typing_extensions import NotRequired as _NotRequired, Annotated as _Annotated
from langgraph.graph.message import add_messages as _add_messages
from langgraph.managed.is_last_step import RemainingStepsManager as _RemainingSteps


class GISAgentState(_TypedDict, total=False):
    """DEPRECATED: Use GISPipelineState."""
    session_id: str
    village_name: str
    reports: _Annotated[Dict[str, Dict[str, Any]], lambda x, y: {**x, **y}]
    summaries: Dict[str, Dict[str, Any]]
    gis_data: Dict[str, Optional[Dict[str, Any]]]
    kg_turtle: str
    kg_constraints: List[Dict[str, Any]]
    layout_configs: List[Dict[str, Any]]
    allocated_geojson: Dict[str, Any]
    allocation_summary: Dict[str, Any]
    intent: Dict[str, Any]
    intent_json: Dict[str, Any]
    messages: _Annotated[List[BaseMessage], _add_messages]
    remaining_steps: _NotRequired[_Annotated[int, _RemainingSteps]]


class ParseAgentState(_TypedDict, total=False):
    """DEPRECATED: Use GISPipelineState."""
    session_id: str
    village_name: str
    reports: _Annotated[Dict[str, Dict[str, Any]], lambda x, y: {**x, **y}]
    summaries: Dict[str, Dict[str, Any]]
    gis_data: Dict[str, Optional[Dict[str, Any]]]
    intent_json: Dict[str, Any]
    messages: _Annotated[List[BaseMessage], _add_messages]
    remaining_steps: _NotRequired[_Annotated[int, _RemainingSteps]]


class LayoutAgentState(_TypedDict, total=False):
    """DEPRECATED: Use GISPipelineState."""
    session_id: str
    village_name: str
    reports: _Annotated[Dict[str, Dict[str, Any]], lambda x, y: {**x, **y}]
    summaries: Dict[str, Dict[str, Any]]
    gis_data: Dict[str, Optional[Dict[str, Any]]]
    intent: Dict[str, Any]
    kg_turtle: str
    kg_constraints: List[Dict[str, Any]]
    layout_configs: List[Dict[str, Any]]
    allocated_geojson: Dict[str, Any]
    allocation_summary: Dict[str, Any]
    messages: _Annotated[List[BaseMessage], _add_messages]
    remaining_steps: _NotRequired[_Annotated[int, _RemainingSteps]]


class LayoutPipelineState(_TypedDict, total=False):
    """DEPRECATED: Use GISPipelineState."""
    session_id: str
    village_name: str
    gis_data: Dict[str, Optional[Dict[str, Any]]]
    intent: Dict[str, Any]
    kg_turtle: str
    kg_constraints: List[Dict[str, Any]]
    allocated_geojson: Dict[str, Any]
    allocation_summary: Dict[str, Any]
    layout_configs: List[Dict[str, Any]]
    validation_result: Dict[str, Any]
    validation_round: int
    export_result: Dict[str, Any]
    render_result: List[Dict[str, Any]]
    messages: _Annotated[List[BaseMessage], _add_messages]


__all__ = [
    "GISPipelineInput",
    "GISPipelineOutput",
    "GISPipelineState",
    # Legacy aliases
    "GISAgentState",
    "ParseAgentState",
    "LayoutAgentState",
    "LayoutPipelineState",
]
