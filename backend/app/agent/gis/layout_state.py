"""LAYOUT Agent state definition."""

from typing import Any, Dict, List, Optional, TypedDict
from typing_extensions import Annotated, NotRequired
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from langgraph.managed.is_last_step import RemainingStepsManager


class LayoutAgentState(TypedDict, total=False):
    """State for the LAYOUT Agent subgraph.

    Focused on spatial reasoning: KG, zone allocation, layout generation,
    and validation. Receives intent from PARSE Agent via state injection.
    """

    # Input (from main graph + PARSE Agent output)
    session_id: str
    village_name: str
    reports: Dict[str, Dict[str, Any]]
    summaries: Dict[str, Dict[str, Any]]
    gis_data: Dict[str, Optional[Dict[str, Any]]]
    intent: Dict[str, Any]

    # KG serialization (build_knowledge_graph writes via Command)
    kg_turtle: str
    kg_constraints: List[Dict[str, Any]]

    # Layout output (tools write via Command)
    layout_configs: List[Dict[str, Any]]
    allocated_geojson: Dict[str, Any]
    allocation_summary: Dict[str, Any]

    # ReAct loop state
    messages: Annotated[List[BaseMessage], add_messages]
    remaining_steps: NotRequired[Annotated[int, RemainingStepsManager]]
