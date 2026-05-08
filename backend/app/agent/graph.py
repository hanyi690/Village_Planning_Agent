"""
村庄规划主图 - 简化版（3节点）

节点：
1. conversation: 中央路由（大脑）
2. execute_tools: 工具执行
3. analyze_dimension: 维度分析
"""

from typing import Dict, Any, Union, List
from langgraph.graph import StateGraph, END, START

from .state import AgentState, PlanningPhase, create_initial_state, get_layer_dimensions
from .routing import after_conversation, after_analysis
from .nodes import conversation_node, execute_tools_node, analyze_dimension, DIMENSION_NAMES

from ..utils.logger import get_logger
logger = get_logger(__name__)

_cached_graph = None
_graph_checkpointer_ref = None


async def analyze_dimension_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """维度分析节点"""
    return await analyze_dimension(state)


def create_unified_planning_graph(checkpointer=None) -> StateGraph:
    """创建统一规划图（3节点）"""
    global _cached_graph, _graph_checkpointer_ref

    if _cached_graph is not None and _graph_checkpointer_ref is checkpointer:
        return _cached_graph

    logger.info("[图构建] 构建3节点图")
    builder = StateGraph(dict)

    builder.add_node("conversation", conversation_node)
    builder.add_node("execute_tools", execute_tools_node)
    builder.add_node("analyze_dimension", analyze_dimension_node)

    builder.add_edge(START, "conversation")
    builder.add_conditional_edges("conversation", after_conversation,
        {"execute_tools": "execute_tools", "analyze_dimension": "analyze_dimension", END: END})
    builder.add_edge("execute_tools", "conversation")
    builder.add_conditional_edges("analyze_dimension", after_analysis,
        {"analyze_dimension": "analyze_dimension", "conversation": "conversation", END: END})

    graph = builder.compile(checkpointer=checkpointer)
    _cached_graph = graph
    _graph_checkpointer_ref = checkpointer
    return graph


def run_unified_planning(session_id, project_name, village_data,
                         task_description="制定村庄总体规划方案",
                         constraints="无特殊约束", checkpointer=None):
    """执行统一规划流程（同步）"""
    graph = create_unified_planning_graph(checkpointer)
    initial_state = create_initial_state(session_id, project_name, village_data, task_description, constraints)
    return graph.invoke(initial_state)


async def run_unified_planning_async(session_id, project_name, village_data,
                                     task_description="制定村庄总体规划方案",
                                     constraints="无特殊约束", checkpointer=None, config=None):
    """执行统一规划流程（异步）"""
    graph = create_unified_planning_graph(checkpointer)
    initial_state = create_initial_state(session_id, project_name, village_data, task_description, constraints)
    invoke_config = {"configurable": config} if config else {}
    return await graph.ainvoke(initial_state, config=invoke_config)


def resume_from_checkpoint(checkpoint_id, session_id, checkpointer=None):
    """从检查点恢复执行"""
    graph = create_unified_planning_graph(checkpointer)
    return graph.invoke(None, {"configurable": {"thread_id": session_id, "checkpoint_id": checkpoint_id}})


__all__ = [
    "AgentState", "PlanningPhase",
    "create_unified_planning_graph", "run_unified_planning",
    "run_unified_planning_async", "resume_from_checkpoint",
]