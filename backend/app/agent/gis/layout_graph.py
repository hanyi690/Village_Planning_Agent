"""LAYOUT Agent graph builder.

Creates a LangGraph ReAct Agent focused on spatial reasoning:
KG construction, constraint querying, zone allocation, layout generation,
and validation. Receives intent from PARSE Agent via state injection.
"""

from langgraph.prebuilt import create_react_agent
from langchain_openai import ChatOpenAI

from app.utils.logger import get_logger

logger = get_logger(__name__)

_cached_graph = None


def create_layout_agent_graph():
    """Create LAYOUT Agent subgraph.

    ReAct agent with 11 tools (7 layout + 4 data) for spatial planning.
    Intent is injected from PARSE Agent output.
    """
    global _cached_graph
    if _cached_graph is not None:
        return _cached_graph

    from app.tools.gis.layout_tools import (
        build_knowledge_graph,
        query_knowledge_graph,
        detect_conflicts,
        allocate_zones,
        generate_layout,
        validate_layout,
        measure_divergence,
    )
    from app.tools.gis.data_tools import (
        fetch_gis_data,
        calculate_gis_coverage,
        analyze_accessibility,
        search_poi,
    )
    from .prompts import LAYOUT_AGENT_SYSTEM_PROMPT
    from .layout_state import LayoutAgentState
    from app.core.settings import LLM_MODEL

    llm = ChatOpenAI(model=LLM_MODEL, temperature=0)

    tools = [
        # Layout tools (7)
        build_knowledge_graph,
        query_knowledge_graph,
        detect_conflicts,
        allocate_zones,
        generate_layout,
        validate_layout,
        measure_divergence,
        # Data tools (4)
        fetch_gis_data,
        calculate_gis_coverage,
        analyze_accessibility,
        search_poi,
    ]

    graph = create_react_agent(
        llm,
        tools,
        state_schema=LayoutAgentState,
        prompt=LAYOUT_AGENT_SYSTEM_PROMPT,
    )

    _cached_graph = graph
    logger.info("[LAYOUT Agent] ReAct agent graph created with %d tools", len(tools))
    return graph
