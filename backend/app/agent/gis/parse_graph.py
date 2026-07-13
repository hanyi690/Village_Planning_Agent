"""PARSE Agent graph builder.

Creates a LangGraph ReAct Agent focused on text understanding:
extracting structured spatial intent from planning reports.
"""

from langgraph.prebuilt import create_react_agent
from langchain_openai import ChatOpenAI

from app.utils.logger import get_logger

logger = get_logger(__name__)

_cached_graph = None


def create_parse_agent_graph():
    """Create PARSE Agent subgraph.

    Single-tool ReAct agent for planning text parsing.
    Output (intent_json) flows to LAYOUT Agent via state injection.
    """
    global _cached_graph
    if _cached_graph is not None:
        return _cached_graph

    from app.tools.gis.layout_tools import parse_planning_text
    from .prompts import PARSE_AGENT_SYSTEM_PROMPT
    from .parse_state import ParseAgentState
    from app.core.settings import LLM_MODEL

    llm = ChatOpenAI(model=LLM_MODEL, temperature=0.2)

    graph = create_react_agent(
        llm,
        [parse_planning_text],
        state_schema=ParseAgentState,
        prompt=PARSE_AGENT_SYSTEM_PROMPT,
    )

    _cached_graph = graph
    logger.info("[PARSE Agent] ReAct agent graph created with 1 tool")
    return graph
