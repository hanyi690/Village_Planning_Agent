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


async def explore_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """EXPLORE 桥接节点 — L3 完成后读 L1/L2/L3 + KG 认知，产出空间定位指令."""
    from app.agent.explore.node import explore_node as _explore_node

    return await _explore_node(state)


def create_unified_planning_graph(checkpointer=None) -> StateGraph:
    """创建统一规划图（6 节点）— 纯函数，每次返回新图。

    缓存责任由调用方承担（`PlanningRuntimeService._graph` 单例）。
    """
    logger.info("[图构建] 构建 6 节点图")
    builder = StateGraph(AgentState)

    builder.add_node("conversation", conversation_node)
    builder.add_node("execute_tools", execute_tools_node)
    builder.add_node("analyze_dimension", analyze_dimension_node)
    builder.add_node("layer_completion_check", layer_completion_check)
    builder.add_node("explore", explore_node)
    builder.add_node("gis_agent", gis_agent_node, error_handler=_gis_error_handler)

    builder.add_edge(START, "conversation")
    builder.add_conditional_edges("conversation", after_conversation,
        {"execute_tools": "execute_tools", "analyze_dimension": "analyze_dimension",
         "gis_agent": "gis_agent", END: END})
    builder.add_edge("execute_tools", "conversation")
    builder.add_edge("gis_agent", END)
    builder.add_edge("analyze_dimension", "layer_completion_check")
    builder.add_edge("explore", "gis_agent")
    builder.add_conditional_edges("layer_completion_check", after_analysis,
        {"analyze_dimension": "analyze_dimension", "explore": "explore",
         "conversation": "conversation", END: END})

    return builder.compile(checkpointer=checkpointer)


__all__ = [
    "AgentState", "PlanningPhase",
    "create_unified_planning_graph",
    "gis_agent_node",
]
