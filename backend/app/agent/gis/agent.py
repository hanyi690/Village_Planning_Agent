"""GIS Agent builders — single, parse, and layout ReAct agents.

Merged from: graph.py + parse_graph.py + layout_graph.py
"""

from langgraph.prebuilt import create_react_agent
from langchain_openai import ChatOpenAI
from app.utils.logger import get_logger

logger = get_logger(__name__)

_cached_gis = None
_cached_parse = None
_cached_layout = None


def create_gis_agent_graph():
    """Single ReAct Agent (fallback) — all 13 tools in one agent."""
    global _cached_gis
    if _cached_gis is not None:
        return _cached_gis

    from app.tools.gis import GIS_TOOLS
    from .prompts import GIS_AGENT_SYSTEM_PROMPT
    from .state import GISAgentState
    from app.core.settings import LLM_MODEL

    llm = ChatOpenAI(model=LLM_MODEL, temperature=0)
    graph = create_react_agent(llm, GIS_TOOLS, state_schema=GISAgentState, prompt=GIS_AGENT_SYSTEM_PROMPT)
    _cached_gis = graph
    logger.info("[GIS Agent] Created with %d tools", len(GIS_TOOLS))
    return graph


def create_parse_agent_graph():
    """PARSE Agent — single-tool: parse_planning_text."""
    global _cached_parse
    if _cached_parse is not None:
        return _cached_parse

    from app.tools.gis.parse import parse_planning_text
    from .prompts import PARSE_AGENT_SYSTEM_PROMPT
    from .state import ParseAgentState
    from app.core.settings import LLM_MODEL

    llm = ChatOpenAI(model=LLM_MODEL, temperature=0.2)
    graph = create_react_agent(llm, [parse_planning_text], state_schema=ParseAgentState, prompt=PARSE_AGENT_SYSTEM_PROMPT)
    _cached_parse = graph
    logger.info("[PARSE Agent] Created with 1 tool")
    return graph


def create_layout_agent_graph():
    """LAYOUT Agent — 11 tools for spatial planning."""
    global _cached_layout
    if _cached_layout is not None:
        return _cached_layout

    from app.tools.gis.kg import build_knowledge_graph, query_knowledge_graph
    from app.tools.gis.conflict import detect_conflicts
    from app.tools.gis.allocate import allocate_zones
    from app.tools.gis.generate import generate_layout
    from app.tools.gis.validate import validate_layout
    from app.tools.gis.export import export_gdb
    from app.tools.gis.render import render_map
    from app.tools.gis.data import fetch_gis_data, search_poi
    from app.tools.gis.analytics import calculate_gis_coverage, analyze_accessibility
    from .prompts import LAYOUT_AGENT_SYSTEM_PROMPT
    from .state import LayoutAgentState
    from app.core.settings import LLM_MODEL

    llm = ChatOpenAI(model=LLM_MODEL, temperature=0)
    tools = [
        build_knowledge_graph, query_knowledge_graph,
        detect_conflicts, allocate_zones, generate_layout, validate_layout,
        export_gdb, render_map,
        fetch_gis_data, calculate_gis_coverage, analyze_accessibility, search_poi,
    ]
    graph = create_react_agent(llm, tools, state_schema=LayoutAgentState, prompt=LAYOUT_AGENT_SYSTEM_PROMPT)
    _cached_layout = graph
    logger.info("[LAYOUT Agent] Created with %d tools", len(tools))
    return graph
