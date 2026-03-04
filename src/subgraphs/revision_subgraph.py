"""
修复子图 (Revision Subgraph)

基于原图的波次路由机制，实现修复任务的并行处理。

关键特性：
1. 使用 LangGraph Send 机制实现并行修复
2. 复用 dimension_metadata.py 的依赖关系计算
3. 按 wave 分组执行，确保依赖顺序正确
4. 支持状态筛选，每个维度只接收依赖的上下文
5. 支持 SSE 事件发送，实时反馈修复进度

架构：
    START
      ↓
    initialize_revision（解析反馈，按 wave 分组维度）
      ↓
    route_by_wave（波次路由）
      ↓
    [revise_single_dimension]*（并行修复多个维度）
      ↓
    reduce_results（汇总修复结果）
      ↓
    check_more_waves（检查是否还有更多波次）
      ↓
    END
"""

from typing import TypedDict, List, Dict, Any, Literal, Union, Optional
from typing_extensions import Annotated
from langgraph.graph import StateGraph, END, START
from langgraph.types import Send
from langgraph.graph.message import add_messages
from langchain_core.messages import BaseMessage, AIMessage, HumanMessage
import operator
from datetime import datetime

from ..config.dimension_metadata import (
    get_full_dependency_chain_func,
    get_dimension_layer,
    get_analysis_dimension_names,
    get_concept_dimension_names,
    get_detailed_dimension_names,
    get_revision_wave_dimensions,
    get_dimension_config,
)
from ..core.config import LLM_MODEL, MAX_TOKENS
from ..utils.logger import get_logger

logger = get_logger(__name__)


# ==========================================
# 子图状态定义
# ==========================================

class RevisionState(TypedDict):
    """修复子图的状态"""
    # 输入数据
    project_name: str
    feedback: str                          # 用户反馈
    target_dimensions: List[str]           # 用户选择要修复的维度
    
    # 现有报告（用于状态筛选和更新）
    analysis_reports: Dict[str, str]       # Layer 1 现状分析报告
    concept_reports: Dict[str, str]        # Layer 2 规划思路报告
    detail_reports: Dict[str, str]         # Layer 3 详细规划报告
    
    # 任务控制
    completed_dimensions: List[str]        # 已完成的维度（用于过滤）
    current_wave: int                      # 当前执行波次
    max_wave: int                          # 最大波次数
    
    # 并行执行结果
    revision_results: Annotated[List[Dict[str, Any]], operator.add]  # 修复结果列表
    
    # 输出数据
    updated_reports: Dict[str, str]        # 更新后的报告 {dimension: new_content}
    revision_history: List[Dict[str, Any]] # 修订历史记录
    
    # SSE 事件跟踪
    sent_revised_events: set               # 已发送的 dimension_revised 事件（去重）


class RevisionDimensionState(TypedDict):
    """单个维度修复的状态（用于并行节点）"""
    dimension_key: str
    dimension_name: str
    project_name: str
    feedback: str
    original_content: str
    # 筛选后的上下文
    filtered_analysis: str
    filtered_concept: str
    filtered_detail: str
    # 依赖链信息
    dependency_chain: dict


# ==========================================
# LLM 调用辅助函数
# ==========================================

def _get_llm():
    """获取 LLM 实例"""
    from ..core.llm_factory import create_llm
    return create_llm(model=LLM_MODEL, temperature=0.7, max_tokens=MAX_TOKENS)


# ==========================================
# 初始化节点
# ==========================================

def initialize_revision(state: RevisionState) -> Dict[str, Any]:
    """
    初始化修复任务
    
    1. 计算所有需要修复的维度（目标维度 + 下游依赖）
    2. 按 wave 分组
    3. 初始化执行状态
    """
    logger.info("[Revision-初始化] 开始初始化修复任务")
    
    target_dimensions = state.get("target_dimensions", [])
    completed_dimensions = state.get("completed_dimensions", [])
    feedback = state.get("feedback", "")
    
    logger.info(f"[Revision-初始化] 目标维度: {target_dimensions}")
    logger.info(f"[Revision-初始化] 用户反馈: {feedback[:100]}...")
    
    # 获取按 wave 分组的待修复维度
    wave_dimensions = get_revision_wave_dimensions(target_dimensions, completed_dimensions)
    
    if not wave_dimensions:
        logger.warning("[Revision-初始化] 没有待修复的维度")
        return {
            "current_wave": 1,
            "max_wave": 0,
            "updated_reports": {},
            "revision_history": []
        }
    
    min_wave = min(wave_dimensions.keys())
    max_wave = max(wave_dimensions.keys())
    logger.info(f"[Revision-初始化] Wave 分布: {[(w, len(d)) for w, d in wave_dimensions.items()]}")
    logger.info(f"[Revision-初始化] Wave 范围: {min_wave} - {max_wave}")
    
    return {
        "current_wave": min_wave,  # 从最小 wave 开始（可能是 0，包含目标维度）
        "max_wave": max_wave,
        "completed_dimensions": completed_dimensions.copy(),
        "updated_reports": {},
        "revision_history": [],
        "sent_revised_events": set()
    }


# ==========================================
# 波次路由函数
# ==========================================

def route_by_wave(state: RevisionState) -> Union[List[Send], str]:
    """
    基于波次的动态路由
    
    检查当前 wave 是否有待处理的维度：
    - 有：返回 Send 列表，触发并行修复
    - 无：推进到下一 wave 或结束
    """
    current_wave = state.get("current_wave", 1)
    max_wave = state.get("max_wave", 0)
    
    logger.info(f"[Revision-路由] 当前 Wave: {current_wave}/{max_wave}")
    
    if current_wave > max_wave:
        logger.info("[Revision-路由] 所有 Wave 完成，结束")
        return END
    
    # 获取当前 wave 的维度（重新计算以获取最新状态）
    target_dimensions = state.get("target_dimensions", [])
    completed = state.get("completed_dimensions", [])
    wave_dimensions = get_revision_wave_dimensions(target_dimensions, completed)
    
    current_wave_dims = wave_dimensions.get(current_wave, [])
    
    if not current_wave_dims:
        logger.info(f"[Revision-路由] Wave {current_wave} 无待处理维度，推进")
        return "advance_wave"
    
    # 过滤已处理的维度
    processed = set(state.get("updated_reports", {}).keys())
    pending_dims = [d for d in current_wave_dims if d not in processed]
    
    if not pending_dims:
        logger.info(f"[Revision-路由] Wave {current_wave} 已完成，推进")
        return "advance_wave"
    
    logger.info(f"[Revision-路由] Wave {current_wave}: {len(pending_dims)} 个维度并行执行")
    
    # 创建并行任务
    return create_parallel_revision_tasks(state, pending_dims)


def create_parallel_revision_tasks(
    state: RevisionState,
    dimensions: List[str]
) -> List[Send]:
    """
    创建并行修复任务，每个任务携带筛选后的状态
    
    复用原图的状态筛选逻辑，确保每个维度只接收其依赖的上下文
    """
    sends = []
    
    analysis_reports = state.get("analysis_reports", {})
    concept_reports = state.get("concept_reports", {})
    detail_reports = state.get("detail_reports", {})
    
    for dim in dimensions:
        # 获取依赖链
        chain = get_full_dependency_chain_func(dim)
        
        # 筛选 Layer 1 现状分析
        required_analyses = chain.get("layer1_analyses", [])
        filtered_analysis_parts = []
        for k in required_analyses:
            if k in analysis_reports:
                name = get_analysis_dimension_names().get(k, k)
                filtered_analysis_parts.append(f"### {name}\n\n{analysis_reports[k]}\n")
        filtered_analysis = "\n".join(filtered_analysis_parts) if filtered_analysis_parts else ""
        
        # 筛选 Layer 2 规划思路
        required_concepts = chain.get("layer2_concepts", [])
        filtered_concept_parts = []
        for k in required_concepts:
            if k in concept_reports:
                name = get_concept_dimension_names().get(k, k)
                filtered_concept_parts.append(f"### {name}\n\n{concept_reports[k]}\n")
        filtered_concept = "\n".join(filtered_concept_parts) if filtered_concept_parts else ""
        
        # 筛选 Layer 3 前序详细规划
        required_details = chain.get("layer3_plans", [])
        filtered_detail_parts = []
        for k in required_details:
            if k in detail_reports:
                name = get_detailed_dimension_names().get(k, k)
                filtered_detail_parts.append(f"### {name}\n\n{detail_reports[k]}\n")
        filtered_detail = "\n".join(filtered_detail_parts) if filtered_detail_parts else ""
        
        # 获取原始内容
        layer = get_dimension_layer(dim)
        if layer == 1:
            original_content = analysis_reports.get(dim, "")
        elif layer == 2:
            original_content = concept_reports.get(dim, "")
        else:
            original_content = detail_reports.get(dim, "")
        
        # 获取维度名称
        config = get_dimension_config(dim)
        dimension_name = config.get("name", dim) if config else dim
        
        # 构建维度状态
        dimension_state = RevisionDimensionState({
            "dimension_key": dim,
            "dimension_name": dimension_name,
            "project_name": state.get("project_name", ""),
            "feedback": state.get("feedback", ""),
            "original_content": original_content,
            "filtered_analysis": filtered_analysis,
            "filtered_concept": filtered_concept,
            "filtered_detail": filtered_detail,
            "dependency_chain": chain
        })
        
        sends.append(Send("revise_single_dimension", dimension_state))
        
        logger.info(f"[Revision-状态筛选] {dim}: "
                   f"现状 {len(required_analyses)} 个 ({len(filtered_analysis)}字符), "
                   f"思路 {len(required_concepts)} 个 ({len(filtered_concept)}字符), "
                   f"前序 {len(required_details)} 个 ({len(filtered_detail)}字符)")
    
    return sends


# ==========================================
# 单维度修复节点
# ==========================================

def revise_single_dimension(state: RevisionDimensionState) -> Dict[str, Any]:
    """
    修复单个维度
    
    使用 GenericPlanner 统一架构执行修复
    """
    dimension_key = state["dimension_key"]
    dimension_name = state["dimension_name"]
    feedback = state["feedback"]
    original_content = state["original_content"]
    
    logger.info(f"[Revision-修复] 开始修复 {dimension_name} ({dimension_key})")
    
    if not original_content:
        logger.warning(f"[Revision-修复] 维度 {dimension_key} 没有原始内容，跳过")
        return {
            "revision_results": [{
                "dimension_key": dimension_key,
                "dimension_name": dimension_name,
                "success": False,
                "error": "原始内容不存在"
            }]
        }
    
    try:
        # 使用 GenericPlanner 进行修复
        from ..planners.generic_planner import GenericPlannerFactory
        planner = GenericPlannerFactory.create_planner(dimension_key)
        
        # 构建规划器状态
        planner_state = {
            "project_name": state.get("project_name", ""),
            "filtered_analysis": state.get("filtered_analysis", ""),
            "filtered_concept": state.get("filtered_concept", ""),
            "filtered_detail": state.get("filtered_detail", ""),
            "task_description": "根据反馈修订规划内容",
            "constraints": feedback
        }
        
        # 执行修复（带反馈）
        revised_result = planner.execute_with_feedback(
            state=planner_state,
            feedback=feedback,
            original_result=original_content,
            revision_count=0
        )
        
        logger.info(f"[Revision-修复] 维度 {dimension_key} 修复完成，内容长度: {len(revised_result)}")
        
        return {
            "revision_results": [{
                "dimension_key": dimension_key,
                "dimension_name": dimension_name,
                "success": True,
                "revised_content": revised_result,
                "original_content": original_content
            }]
        }
        
    except Exception as e:
        logger.error(f"[Revision-修复] 维度 {dimension_key} 修复失败: {e}")
        return {
            "revision_results": [{
                "dimension_key": dimension_key,
                "dimension_name": dimension_name,
                "success": False,
                "error": str(e)
            }]
        }


# ==========================================
# 结果汇总节点
# ==========================================

def reduce_revision_results(state: RevisionState) -> Dict[str, Any]:
    """
    汇总修复结果
    
    1. 更新 updated_reports
    2. 更新 completed_dimensions
    3. 记录修订历史
    """
    logger.info(f"[Revision-汇总] 汇总 {len(state.get('revision_results', []))} 个修复结果")
    
    revision_results = state.get("revision_results", [])
    updated_reports = dict(state.get("updated_reports", {}))
    completed_dimensions = list(state.get("completed_dimensions", []))
    revision_history = list(state.get("revision_history", []))
    
    for result in revision_results:
        dim = result.get("dimension_key")
        if result.get("success"):
            revised_content = result.get("revised_content", "")
            original_content = result.get("original_content", "")
            
            # 更新报告
            updated_reports[dim] = revised_content
            
            # 标记完成
            if dim not in completed_dimensions:
                completed_dimensions.append(dim)
            
            # 记录历史
            revision_history.append({
                "dimension": dim,
                "dimension_name": result.get("dimension_name", dim),
                "old_content": original_content,
                "new_content": revised_content,
                "timestamp": datetime.now().isoformat()
            })
            
            logger.info(f"[Revision-汇总] 维度 {dim} 更新完成")
    
    return {
        "updated_reports": updated_reports,
        "completed_dimensions": completed_dimensions,
        "revision_history": revision_history,
        "revision_results": []  # 清空，为下一波次准备
    }


# ==========================================
# 波次推进节点
# ==========================================

def advance_wave(state: RevisionState) -> Dict[str, Any]:
    """推进到下一个波次"""
    current_wave = state.get("current_wave", 1)
    next_wave = current_wave + 1
    
    logger.info(f"[Revision-推进] Wave {current_wave} → Wave {next_wave}")
    
    return {"current_wave": next_wave}


# ==========================================
# 检查是否完成
# ==========================================

def check_revision_complete(state: RevisionState) -> Literal["continue", "end"]:
    """
    检查修复是否完成
    
    Returns:
        "continue": 继续下一波次
        "end": 所有波次完成，结束
    """
    current_wave = state.get("current_wave", 1)
    max_wave = state.get("max_wave", 0)
    
    if current_wave > max_wave:
        logger.info("[Revision-检查] 所有波次完成")
        return "end"
    
    return "continue"


# ==========================================
# 构建子图
# ==========================================

def create_revision_subgraph() -> StateGraph:
    """
    创建修复子图（基于波次的动态路由版本）
    
    Returns:
        编译后的 StateGraph 实例
    """
    logger.info("[Revision-子图构建] 开始构建修复子图（波次动态路由版本）")
    
    # 创建状态图
    builder = StateGraph(RevisionState)
    
    # 添加节点
    builder.add_node("initialize", initialize_revision)
    builder.add_node("revise_single_dimension", revise_single_dimension)
    builder.add_node("reduce_results", reduce_revision_results)
    builder.add_node("advance_wave", advance_wave)
    
    # 构建执行流程
    builder.add_edge(START, "initialize")
    
    # 初始化 -> 波次路由决策
    builder.add_conditional_edges(
        "initialize",
        route_by_wave,
        ["revise_single_dimension", "advance_wave", END]
    )
    
    # 修复节点 -> 汇总
    builder.add_edge("revise_single_dimension", "reduce_results")
    
    # 汇总 -> 检查是否完成
    builder.add_conditional_edges(
        "reduce_results",
        check_revision_complete,
        {
            "continue": "route_next",  # 继续路由
            "end": END
        }
    )
    
    # 添加路由节点（用于再次触发波次路由）
    builder.add_node("route_next", lambda state: {})
    
    # 路由决策（再次使用波次路由函数）
    builder.add_conditional_edges(
        "route_next",
        route_by_wave,
        ["revise_single_dimension", "advance_wave", END]
    )
    
    # 波次推进 -> 再次路由
    builder.add_edge("advance_wave", "route_next")
    
    # 编译子图
    revision_subgraph = builder.compile()
    
    logger.info("[Revision-子图构建] 修复子图构建完成（支持波次动态路由并行执行）")
    
    return revision_subgraph


# ==========================================
# 子图包装函数（用于父图调用）
# ==========================================

def call_revision_subgraph(
    project_name: str,
    feedback: str,
    target_dimensions: List[str],
    analysis_reports: Dict[str, str] = None,
    concept_reports: Dict[str, str] = None,
    detail_reports: Dict[str, str] = None,
    completed_dimensions: List[str] = None
) -> Dict[str, Any]:
    """
    调用修复子图的包装函数
    
    Args:
        project_name: 项目/村庄名称
        feedback: 用户反馈
        target_dimensions: 要修复的维度列表
        analysis_reports: Layer 1 现状分析报告
        concept_reports: Layer 2 规划思路报告
        detail_reports: Layer 3 详细规划报告
        completed_dimensions: 已完成的维度列表
        
    Returns:
        {
            "success": bool,
            "updated_reports": Dict[str, str],  # 更新后的报告
            "revision_history": List[Dict],     # 修订历史
            "error": str
        }
    """
    logger.info(f"[Revision-子图调用] 开始调用修复子图: {project_name}")
    logger.info(f"[Revision-子图调用] 目标维度: {target_dimensions}")
    
    # 创建子图实例
    subgraph = create_revision_subgraph()
    
    # 构建初始状态
    initial_state: RevisionState = {
        "project_name": project_name,
        "feedback": feedback,
        "target_dimensions": target_dimensions,
        "analysis_reports": analysis_reports or {},
        "concept_reports": concept_reports or {},
        "detail_reports": detail_reports or {},
        "completed_dimensions": completed_dimensions or [],
        "current_wave": 1,
        "max_wave": 0,
        "revision_results": [],
        "updated_reports": {},
        "revision_history": [],
        "sent_revised_events": set()
    }
    
    try:
        # 调用子图
        result = subgraph.invoke(initial_state)
        
        updated_reports = result.get("updated_reports", {})
        revision_history = result.get("revision_history", [])
        
        logger.info(f"[Revision-子图调用] 子图执行成功，更新 {len(updated_reports)} 个维度")
        
        return {
            "success": len(updated_reports) > 0,
            "updated_reports": updated_reports,
            "revision_history": revision_history,
            "completed_dimensions": result.get("completed_dimensions", []),
            "error": ""
        }
        
    except Exception as e:
        logger.error(f"[Revision-子图调用] 子图执行失败: {e}")
        return {
            "success": False,
            "updated_reports": {},
            "revision_history": [],
            "completed_dimensions": [],
            "error": str(e)
        }


__all__ = [
    "RevisionState",
    "RevisionDimensionState",
    "create_revision_subgraph",
    "call_revision_subgraph",
]
