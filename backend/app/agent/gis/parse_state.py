"""PARSE Agent state definition."""

from typing import Any, Dict, List, Optional, TypedDict
from typing_extensions import Annotated, NotRequired
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from langgraph.managed.is_last_step import RemainingStepsManager


class ParseAgentState(TypedDict, total=False):
    """State for the PARSE Agent subgraph.

    Focused on text understanding: extracting structured spatial intent
    from planning reports. Context-isolated from LAYOUT Agent.
    """

    # Input (from main graph)
    session_id: str
    village_name: str
    reports: Dict[str, Dict[str, Any]]
    summaries: Dict[str, Dict[str, Any]]
    gis_data: Dict[str, Optional[Dict[str, Any]]]

    # Output (parse_planning_text writes via Command)
    intent_json: Dict[str, Any]

    # ReAct loop state
    messages: Annotated[List[BaseMessage], add_messages]
    remaining_steps: NotRequired[Annotated[int, RemainingStepsManager]]
