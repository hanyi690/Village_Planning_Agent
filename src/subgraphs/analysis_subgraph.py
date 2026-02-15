"""
现状分析子图 (Analysis Subgraph)

实现村庄现状分析的12个维度并行分析，使用 LangGraph 的 Send 机制实现 Map-Reduce 模式。
集成两阶段RAG系统，支持知识预加载优化。

12个分析维度：
1. 区位分析
2. 社会经济分析
3. 村民意愿与诉求分析
4. 上位规划与政策导向分析
5. 自然环境分析
6. 土地利用分析
7. 道路交通分析
8. 公共服务设施分析
9. 基础设施分析
10. 生态绿地分析
11. 建筑分析
12. 历史文化分析
"""

from typing import TypedDict, List, Dict, Any, Literal
from typing_extensions import Annotated
from langgraph.graph import StateGraph, END, START
from langgraph.types import Send
from langgraph.graph.message import add_messages
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage
import operator

from ..core.config import LLM_MODEL, MAX_TOKENS
from ..utils.logger import get_logger
from .analysis_prompts import get_dimension_prompt, ANALYSIS_SUMMARY_PROMPT, list_dimensions

# RAG imports (conditional)
try:
    from ..orchestration.knowledge_preloader import KnowledgePreloader, format_dimension_knowledge
    RAG_AVAILABLE = True
except ImportError:
    RAG_AVAILABLE = False
    KnowledgePreloader = None  # type: ignore
    format_dimension_knowledge = None  # type: ignore
    logger = get_logger(__name__)
    logger.warning("[RAG集成] 知识预加载器不可用，将使用传统模式")


def merge_dicts(left: Dict[str, str], right: Dict[str, str]) -> Dict[str, str]:
    """合并两个字典"""
    result = {**left, **right}
    logger.info(f"[merge_dicts] 合并字典: 左={len(left)}项, 右={len(right)}项 -> 结果={len(result)}项")
    return result

# ==========================================
# 子图状态定义
# ==========================================

class AnalysisState(TypedDict):
    """现状分析子图的状态"""
    # 输入数据
    raw_data: str  # 原始村庄数据
    project_name: str  # 项目名称

    # 中间状态 - 用于并行分析
    subjects: List[str]  # 待分析的维度列表
    analyses: Annotated[List[Dict[str, str]], operator.add]  # 已完成的维度分析（使用add累加）

    # 输出数据 - 只保留维度报告（使用自定义合并函数合并各维度的结果）
    analysis_dimension_reports: Annotated[Dict[str, str], merge_dicts]  # 各维度独立报告

    # 消息历史（用于LLM交互）
    messages: Annotated[List[BaseMessage], add_messages]

    # RAG知识预加载（新增）
    knowledge_map: Dict[str, List[dict]]  # 预加载的知识映射
    rag_enabled: bool  # 是否启用RAG


class DimensionAnalysisState(TypedDict):
    """单个维度分析的状态（用于并行节点）"""
    dimension_key: str  # 维度标识
    dimension_name: str  # 维度名称
    raw_data: str  # 原始数据
    analysis_result: str  # 分析结果


# ==========================================
# LLM 调用辅助函数
# ==========================================

def _get_llm():
    """获取 LLM 实例，使用统一的 LLM 工厂"""
    from ..core.llm_factory import create_llm
    return create_llm(model=LLM_MODEL, temperature=0.7, max_tokens=MAX_TOKENS)


# ==========================================
# Map-Reduce 路由与分发节点
# ==========================================

def map_dimensions(state: AnalysisState) -> List[Send]:
    """
    Map 阶段：将10个维度映射为独立的分析任务

    使用 LangGraph 的 Send 机制，为每个维度创建独立的执行分支。

    Returns:
        Send 对象列表，每个 Send 指向 analyze_dimension 节点并携带独立状态
    """
    logger.info(f"[子图-Map] 开始分发 {len(state['subjects'])} 个分析维度")

    # 为每个维度创建 Send 对象
    sends = []
    for dimension_key in state["subjects"]:
        # 获取维度信息
        dimensions_info = {d["key"]: d for d in list_dimensions()}
        dimension_info = dimensions_info.get(dimension_key, {"name": dimension_key, "description": ""})

        # 创建该维度的独立状态
        dimension_state = {
            "dimension_key": dimension_key,
            "dimension_name": dimension_info["name"],
            "raw_data": state["raw_data"],
            "analysis_result": "",
            # 【流式输出支持】传递流式输出配置
            "_streaming_enabled": state.get("_streaming_enabled", False),
            "_token_callback_factory": state.get("_token_callback_factory")
        }

        # 创建 Send 对象：发送到 analyze_dimension 节点
        sends.append(Send("analyze_dimension", dimension_state))

    logger.info(f"[子图-Map] 创建了 {len(sends)} 个并行任务")
    return sends


# 【已删除】reduce_analyses 函数 - 不再需要汇总节点
# 【已删除】generate_final_report 函数 - 不再需要生成综合报告

# ==========================================
# 知识预加载节点（新增）
# ==========================================

def knowledge_preload_node(state: AnalysisState) -> Dict[str, Any]:
    """
    知识预加载节点（集成RAG）

    在12维度并行分析前，预加载所有文档摘要到knowledge_map，
    避免各个维度重复检索，大幅提升并行性能。
    （同步包装函数，使用线程池运行异步代码）
    """
    if not RAG_AVAILABLE or not state.get("rag_enabled", False):
        logger.info("[子图-知识预加载] RAG未启用，跳过预加载")
        return {"knowledge_map": {}, "rag_enabled": False}

    try:
        import asyncio
        import concurrent.futures

        preloader = KnowledgePreloader()
        logger.info("[子图-知识预加载] 开始预加载知识库...")

        # 使用线程池运行异步函数
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(
                asyncio.run,
                preloader.preload_all_knowledge(state)
            )
            knowledge_map = future.result(timeout=30)

        logger.info(f"[子图-知识预加载] 完成，共{len(knowledge_map)}个维度")

        return {
            "knowledge_map": knowledge_map,
            "rag_enabled": True
        }
    except Exception as e:
        logger.warning(f"[子图-知识预加载] 预加载失败: {e}")
        return {"knowledge_map": {}, "rag_enabled": False}


# ==========================================
# 初始化节点
# ==========================================

def initialize_analysis(state: AnalysisState) -> Dict[str, Any]:
    """
    初始化分析流程，设置待分析的维度列表
    """
    logger.info(f"[子图-初始化] 开始现状分析，项目: {state.get('project_name', '未命名')}")

    # 定义12个分析维度
    all_dimensions = [
        "location",           # 区位分析
        "socio_economic",     # 社会经济分析
        "villager_wishes",    # 村民意愿与诉求分析
        "superior_planning",  # 上位规划与政策导向分析
        "natural_environment", # 自然环境分析
        "land_use",           # 土地利用分析
        "traffic",            # 道路交通分析
        "public_services",    # 公共服务设施分析
        "infrastructure",     # 基础设施分析
        "ecological_green",   # 生态绿地分析
        "architecture",       # 建筑分析
        "historical_culture"  # 历史文化与乡愁保护分析
    ]

    logger.info(f"[子图-初始化] 设置 {len(all_dimensions)} 个分析维度")

    return {
        "subjects": all_dimensions,
        "analyses": [],
        "knowledge_map": {},  # 初始化知识映射
        "rag_enabled": state.get("rag_enabled", RAG_AVAILABLE)  # 传递RAG启用状态
    }


# ==========================================
# 构建子图
# ==========================================

def create_analysis_subgraph() -> StateGraph:
    """
    创建现状分析子图 - 重构版：删除汇总节点，集成知识预加载

    流程：initialize -> knowledge_preload -> map -> analyze_dimension (并行) -> END

    Returns:
        编译后的 StateGraph 实例
    """
    from ..nodes.subgraph_nodes import (
        InitializeAnalysisNode,
        AnalyzeDimensionNode
    )

    logger.info("[子图构建] 开始构建现状分析子图（重构版：无汇总节点 + RAG集成）")

    # 创建状态图
    builder = StateGraph(AnalysisState)

    # 创建节点实例
    initialize_node = InitializeAnalysisNode()
    analyze_node = AnalyzeDimensionNode()

    # 添加节点
    builder.add_node("initialize", initialize_node)
    builder.add_node("knowledge_preload", knowledge_preload_node)  # 新增：知识预加载节点
    builder.add_node("analyze_dimension", analyze_node)

    # 构建执行流程
    builder.add_edge(START, "initialize")
    builder.add_edge("initialize", "knowledge_preload")  # 新增：初始化后预加载知识

    # 关键：使用条件边实现并行分发
    # 在 LangGraph 1.0.x 中，Send 对象必须由路由函数返回，不能由节点返回
    # 路由函数接收状态并返回 Send 对象列表
    def route_to_dimensions(state: AnalysisState) -> List[Send]:
        """路由函数：将状态分发到各维度的分析节点"""
        return map_dimensions(state)

    builder.add_conditional_edges("knowledge_preload", route_to_dimensions)  # 修改：从knowledge_preload分发

    # 【重构】analyze 节点直接到 END，不再经过 reduce 和 generate 节点
    builder.add_edge("analyze_dimension", END)

    # 编译子图
    analysis_subgraph = builder.compile()

    logger.info("[子图构建] 现状分析子图构建完成（重构版：无汇总节点 + RAG集成）")

    return analysis_subgraph


# ==========================================
# 子图包装函数（用于父图调用）
# ==========================================

def call_analysis_subgraph(
    raw_data: str,
    project_name: str = "村庄",
    _streaming_enabled: bool = False,  # 新增：是否启用流式输出
    _token_callback_factory = None,  # 新增：token 回调工厂
    rag_enabled: bool = True,  # 新增：是否启用RAG
    _streaming_queue=None,  # 新增：流式队列管理器
    _storage_pipeline=None,  # 新增：异步存储管道
    _dimension_events=None  # 新增：维度事件列表
) -> Dict[str, Any]:
    """
    调用现状分析子图的包装函数

    这个函数可以在父图中作为一个节点使用，实现"不同状态模式"的调用。
    【重构】只返回维度报告，不生成综合报告
    【流式输出】支持 token 级别的流式输出
    【RAG集成】支持知识预加载

    Args:
        raw_data: 村庄原始数据
        project_name: 项目名称
        _streaming_enabled: 是否启用流式输出
        _token_callback_factory: token 回调工厂函数
        rag_enabled: 是否启用RAG知识检索

    Returns:
        包含维度报告的字典
    """
    logger.info(f"[子图调用] 开始调用现状分析子图: {project_name}")

    # 创建子图实例
    subgraph = create_analysis_subgraph()

    # 构建初始状态
    initial_state: AnalysisState = {
        "raw_data": raw_data,
        "project_name": project_name,
        "subjects": [],
        "analyses": [],
        "analysis_dimension_reports": {},
        "messages": [],
        # 【流式输出支持】传递流式输出配置
        "_streaming_enabled": _streaming_enabled,
        "_token_callback_factory": _token_callback_factory,
        # 【RAG集成】传递RAG启用状态
        "rag_enabled": rag_enabled and RAG_AVAILABLE,
    }

    try:
        # 调用子图
        result = subgraph.invoke(initial_state)

        logger.info(f"[子图调用] 子图执行完成")

        # 【修复】从 analyses 列表中提取维度报告并转换为字典（使用英文键名）
        analyses = result.get("analyses", [])
        dimension_reports = {}

        # ✅ 新增：收集失败的维度
        failed_dimensions = []
        for analysis in analyses:
            dimension_key = analysis.get("dimension_key")  # 使用英文key
            analysis_result = analysis.get("analysis_result")
            if dimension_key and analysis_result:
                dimension_reports[dimension_key] = analysis_result
            elif dimension_key and not analysis_result:
                # 空内容表示失败
                failed_dimensions.append(dimension_key)

        # ✅ 新增：从各维度的返回值中收集失败信息
        # LangGraph 的并行执行会将各节点的返回值合并
        failed_dims_from_result = result.get("_failed_dimensions", [])
        if failed_dims_from_result:
            failed_dimensions.extend([d["dimension_key"] for d in failed_dims_from_result])

        # 去重
        failed_dimensions = list(set(failed_dimensions))

        logger.info(f"[子图调用] 维度报告数量: {len(dimension_reports)}")
        if failed_dimensions:
            logger.warning(f"[子图调用] 失败的维度: {failed_dimensions}")

        # ✅ 关键修改：只有当没有失败维度时才返回 success=True
        all_success = len(failed_dimensions) == 0

        # 返回维度报告字典（键名为英文）
        return {
            "analysis_dimension_reports": dimension_reports,
            "success": all_success,
            "failed_dimensions": failed_dimensions,
            "error": None if all_success else f"{len(failed_dimensions)} 个维度分析失败"
        }

    except Exception as e:
        logger.error(f"[子图调用] 子图执行失败: {str(e)}")
        return {
            "analysis_dimension_reports": {},
            "success": False,
            "failed_dimensions": [],
            "error": str(e)
        }


# ==========================================
# 测试入口
# ==========================================

if __name__ == "__main__":
    # 测试数据
    test_data = """
    村庄名称：某某村
    人口：1200人
    面积：5.2平方公里
    主要产业：农业、旅游业
    """

    # 创建并运行子图
    subgraph = create_analysis_subgraph()

    initial_state = {
        "raw_data": test_data,
        "project_name": "某某村",
        "subjects": [],
        "analyses": [],
        "analysis_dimension_reports": {},
        "messages": []
    }

    print("=== 开始执行现状分析子图 ===\n")

    result = subgraph.invoke(initial_state)

    print("\n=== 执行完成 ===")
    print(f"维度报告数量: {len(result['analysis_dimension_reports'])}")
    print("\n=== 维度报告 ===")
    for dim_name, content in result['analysis_dimension_reports'].items():
        print(f"\n### {dim_name}")
        print(content[:200] + "..." if len(content) > 200 else content)
