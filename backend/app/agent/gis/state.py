"""GIS Agent state definition."""

from typing import Any, Dict, List, Optional, TypedDict
from typing_extensions import Annotated, NotRequired
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from langgraph.managed.is_last_step import RemainingStepsManager


class GISAgentState(TypedDict, total=False):
    """State for the GIS ReAct Agent subgraph.

    Input fields are populated from the main graph state.
    Intermediate fields are shared between tool calls within the ReAct loop.
    """

    # Input (from main graph)
    session_id: str
    village_name: str
    reports: Dict[str, Dict[str, Any]]
    summaries: Dict[str, Dict[str, Any]]

    # GIS data (keyed by type: boundary, landuse_current, protection_zones, road, hazard)
    gis_data: Dict[str, Optional[Dict[str, Any]]]

    # KG serialization — persisted across tool calls within ReAct loop
    kg_turtle: str                            # RDFlib Graph serialized as Turtle
    kg_constraints: List[Dict[str, Any]]      # Extracted constraints (avoid re-query)

    # Agent shared state (tools read/write)
    layout_configs: List[Dict[str, Any]]

    # ReAct loop state (required by create_react_agent)
    messages: Annotated[List[BaseMessage], add_messages]
    remaining_steps: NotRequired[Annotated[int, RemainingStepsManager]]
