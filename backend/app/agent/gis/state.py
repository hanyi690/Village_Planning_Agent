"""GIS Agent state definitions — merged from state.py + parse_state.py + layout_state.py."""

from typing import Any, Dict, List, Optional, TypedDict
from typing_extensions import Annotated, NotRequired
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from langgraph.managed.is_last_step import RemainingStepsManager


class GISAgentState(TypedDict, total=False):
    """Unified state for the single GIS ReAct Agent (fallback)."""
    session_id: str
    village_name: str
    reports: Dict[str, Dict[str, Any]]
    summaries: Dict[str, Dict[str, Any]]
    gis_data: Dict[str, Optional[Dict[str, Any]]]
    kg_turtle: str
    kg_constraints: List[Dict[str, Any]]
    layout_configs: List[Dict[str, Any]]
    allocated_geojson: Dict[str, Any]
    allocation_summary: Dict[str, Any]
    intent: Dict[str, Any]
    intent_json: Dict[str, Any]
    messages: Annotated[List[BaseMessage], add_messages]
    remaining_steps: NotRequired[Annotated[int, RemainingStepsManager]]


class ParseAgentState(TypedDict, total=False):
    """State for PARSE Agent subgraph."""
    session_id: str
    village_name: str
    reports: Dict[str, Dict[str, Any]]
    summaries: Dict[str, Dict[str, Any]]
    gis_data: Dict[str, Optional[Dict[str, Any]]]
    intent_json: Dict[str, Any]
    messages: Annotated[List[BaseMessage], add_messages]
    remaining_steps: NotRequired[Annotated[int, RemainingStepsManager]]


class LayoutAgentState(TypedDict, total=False):
    """State for LAYOUT Agent subgraph."""
    session_id: str
    village_name: str
    reports: Dict[str, Dict[str, Any]]
    summaries: Dict[str, Dict[str, Any]]
    gis_data: Dict[str, Optional[Dict[str, Any]]]
    intent: Dict[str, Any]
    kg_turtle: str
    kg_constraints: List[Dict[str, Any]]
    layout_configs: List[Dict[str, Any]]
    allocated_geojson: Dict[str, Any]
    allocation_summary: Dict[str, Any]
    messages: Annotated[List[BaseMessage], add_messages]
    remaining_steps: NotRequired[Annotated[int, RemainingStepsManager]]


class LayoutPipelineState(TypedDict, total=False):
    """State for LAYOUT hybrid pipeline (StateGraph).

    Deterministic skeleton + ReAct adaptive loop + Worker-Evaluator retry.
    """
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
    messages: Annotated[List[BaseMessage], add_messages]
