"""GIS Agent builders — unified pipeline (primary) + PARSE Agent subgraph.

Architecture (2026-07-17):
  - Primary: build_layout_pipeline() → unified StateGraph with Pydantic state
  - PARSE: build_parse_agent_graph() → spatially-aware semi-structured ReAct subgraph
  - Legacy: create_gis/layout_agent_graph() → deprecated single ReAct agents
"""

from __future__ import annotations

from typing import Any, Dict

from langgraph.prebuilt import create_react_agent
from langchain_openai import ChatOpenAI
from app.utils.logger import get_logger

logger = get_logger(__name__)

_cached_gis = None
_cached_layout = None


def create_parse_agent_graph():
    """PARSE Agent — spatially-aware semi-structured ReAct subgraph.

    Uses StateGraph with:
      - classify_sections -> route_by_section (Send fan-out)
      - extract_regulations/tables/projects/targets (parallel)
      - validate_and_merge (converge + retry loop)

    Returns:
        CompiledStateGraph with ParseAgentState schema.
    """
    from app.agent.gis.parse.agent import build_parse_agent_graph
    return build_parse_agent_graph()


def create_gis_agent_graph():
    """DEPRECATED: Single ReAct Agent (fallback) — all 13 tools in one agent.

    Use build_layout_pipeline() for the new unified StateGraph pipeline.
    Kept for backward compatibility.
    """
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
    logger.info("[GIS Agent - Legacy] Created with %d tools (DEPRECATED)", len(GIS_TOOLS))
    return graph


def create_layout_agent_graph():
    """DEPRECATED: LAYOUT Agent — 11 tools for spatial planning.

    Use build_layout_pipeline() for the new unified StateGraph pipeline.
    Kept for backward compatibility — still used by allocate_generate_react_node.
    """
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
    logger.info("[LAYOUT Agent - Legacy] Created with %d tools (DEPRECATED)", len(tools))
    return graph


# ── NEW: Unified pipeline entry point ──────────────────────────────────


async def run_gis_pipeline(
    session_id: str,
    village_name: str,
    planning_text: str = "",
    l3_reports: Dict[str, Any] = None,
) -> Dict[str, Any]:
    """Run the unified GIS layout pipeline end-to-end.

    This is the RECOMMENDED entry point replacing the legacy 3-agent graph.

    Args:
        session_id: Unique session identifier
        village_name: Target village name (for GIS data lookup)
        planning_text: Markdown planning report (gen path)
        l3_reports: L3 analyzed reports (plan path)

    Returns:
        Pipeline output dict with layout_configs, export_result, render_result, etc.
    """
    from .layout_pipeline import build_layout_pipeline
    from .state import GISPipelineInput

    pipeline = build_layout_pipeline()

    input_data = GISPipelineInput(
        session_id=session_id,
        village_name=village_name,
        planning_text=planning_text,
        l3_reports=l3_reports or {},
    )

    logger.info("[GIS Pipeline] Starting unified pipeline for: %s", village_name)
    result = await pipeline.ainvoke(input_data.model_dump())
    logger.info("[GIS Pipeline] Completed for: %s", village_name)
    return result


__all__ = [
    "create_gis_agent_graph",
    "create_parse_agent_graph",
    "create_layout_agent_graph",
    "run_gis_pipeline",
]
