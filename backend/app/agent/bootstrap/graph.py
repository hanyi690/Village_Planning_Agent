"""Main planning graph factory. Migrated from agent/graph.py per docs/architecture/agent-graph.md §5."""

from typing import Dict, Any, List, Literal, Optional
from langgraph.graph import StateGraph, END, START

from app.agent.plan_state.state import AgentState, create_initial_state
from app.agent.bootstrap.phase_machine import PlanningPhase, get_layer_dimensions
from app.agent.conversation_router import after_conversation, after_analysis, conversation_node
from app.agent.tools import execute_tools_node
from app.agent.l1_observe import analyze_dimension, DIMENSION_NAMES
from app.agent.plan_state import layer_completion_check
from app.agent.bootstrap.gis_agent_entry import gis_agent_node, _gis_error_handler
from app.agent.bootstrap.layer_aggregate_node import layer_aggregate_node

from app.utils.logger import get_logger
logger = get_logger(__name__)


# TimeoutPolicy + error_handler for node-level fault tolerance (LangGraph v1.2)
try:
    from langgraph.types import RetryPolicy
    _HAS_RETRY_POLICY = True
except ImportError:
    _HAS_RETRY_POLICY = False


async def analyze_dimension_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """维度分析节点"""
    return await analyze_dimension(state)


def create_unified_planning_graph(checkpointer=None) -> StateGraph:
    """创建统一规划图 - 纯函数，每次返回新图。

    缓存责任由调用方承担（`PlanningRuntimeService._graph` 单例）。
    Wave M2: explore_node removed (EXPLORE is now gate-driven horizontal service).
    """
    logger.info("[图构建] 构建规划图")
    builder = StateGraph(AgentState)

    builder.add_node("conversation", conversation_node)
    builder.add_node("execute_tools", execute_tools_node)
    builder.add_node("analyze_dimension", analyze_dimension_node)
    builder.add_node("layer_completion_check", layer_completion_check)
    builder.add_node("layer_aggregate", layer_aggregate_node)
    builder.add_node("gis_agent", gis_agent_node, error_handler=_gis_error_handler)

    builder.add_edge(START, "conversation")
    builder.add_conditional_edges("conversation", after_conversation,
        {"execute_tools": "execute_tools", "analyze_dimension": "analyze_dimension",
         "gis_agent": "gis_agent", END: END})
    builder.add_edge("execute_tools", "conversation")
    builder.add_edge("gis_agent", END)
    builder.add_edge("analyze_dimension", "layer_completion_check")
    builder.add_edge("layer_completion_check", "layer_aggregate")
    builder.add_conditional_edges("layer_aggregate", after_analysis,
        {"analyze_dimension": "analyze_dimension",
         "conversation": "conversation", END: END})

    return builder.compile(checkpointer=checkpointer)


__all__ = [
    "AgentState", "PlanningPhase",
    "create_unified_planning_graph",
    "gis_agent_node",
]
