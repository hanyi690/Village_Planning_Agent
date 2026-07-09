"""GIS ReAct Agent graph builder.

Creates a LangGraph ReAct Agent that uses GIS tools for spatial layout planning.
"""

from langgraph.prebuilt import create_react_agent
from app.utils.logger import get_logger

logger = get_logger(__name__)

_cached_graph = None


def create_gis_agent_graph():
    """Create GIS ReAct Agent subgraph.

    Returns a compiled StateGraph with:
    - 10 tools from app.tools.gis (4 data + 6 layout)
    - LLM-driven ReAct loop for spatial layout planning
    - Validation feedback loop
    - Custom state_schema for KG persistence and layout output
    """
    global _cached_graph
    if _cached_graph is not None:
        return _cached_graph

    from app.tools.gis import GIS_TOOLS
    from .prompts import GIS_AGENT_SYSTEM_PROMPT
    from .state import GISAgentState
    from app.core.llm import create_llm

    llm = create_llm(temperature=0, max_tokens=2000)

    graph = create_react_agent(
        llm,
        GIS_TOOLS,
        state_schema=GISAgentState,
        prompt=GIS_AGENT_SYSTEM_PROMPT,
    )

    _cached_graph = graph
    logger.info("[GIS Agent] ReAct agent graph created with %d tools", len(GIS_TOOLS))
    return graph
