"""
现状分析子图 (Analysis Subgraph)

实现村庄现状分析的12个维度并行分析，使用 LangGraph 的 Send 机制实现 Map-Reduce 模式。

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

logger = get_logger(__name__)

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

    # 输出数据（统一命名）
    analysis_reports: Dict[str, str]  # 各维度独立报告（用于部分状态传递）

    # 消息历史（用于LLM交互）
    messages: Annotated[List[BaseMessage], add_messages]


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
# 并行分析节点函数
# ==========================================

def analyze_dimension(state: DimensionAnalysisState) -> Dict[str, Any]:
    """
    执行单个维度的分析

    使用 GenericPlanner 统一架构，充分利用现有的基础设施。

    Args:
        state: 包含维度信息和原始数据的状态

    Returns:
        该维度的分析结果（包装在列表中以支持 operator.add 累加）
    """
    dimension_key = state["dimension_key"]
    dimension_name = state["dimension_name"]

    logger.info(f"[子图-分析] 开始执行 {dimension_name} ({dimension_key})")

    try:
        # 【使用统一架构】使用 GenericPlannerFactory 创建规划器
        from ..planners.generic_planner import GenericPlannerFactory
        planner = GenericPlannerFactory.create_planner(dimension_key)

        # 【使用统一架构】调用规划器的 execute 方法
        # 注意：GenericPlanner 需要完整的状态字典，包含 raw_data
        planner_state = {"raw_data": state["raw_data"], "project_name": state.get("project_name", "村庄")}
        planner_result = planner.execute(planner_state)

        # GenericPlanner 返回的结果键名由 get_result_key() 决定
        result_key = planner.get_result_key()
        analysis_text = planner_result.get(result_key, planner_result.get("analysis_result", ""))
        logger.info(f"[子图-分析] 完成 {dimension_name}，生成 {len(analysis_text)} 字符")

        # 在 LangGraph 1.0.x 中，使用 operator.add 时需要返回列表
        return {
            "analyses": [{
                "dimension_key": dimension_key,
                "dimension_name": dimension_name,
                "analysis_result": analysis_text
            }]
        }

    except Exception as e:
        logger.error(f"[子图-分析] {dimension_name} 执行失败: {str(e)}")
        # 返回错误信息而非崩溃
        return {
            "analyses": [{
                "dimension_key": dimension_key,
                "dimension_name": dimension_name,
                "analysis_result": f"[分析失败] {str(e)}"
            }]
        }


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
            "analysis_result": ""
        }

        # 创建 Send 对象：发送到 analyze_dimension 节点
        sends.append(Send("analyze_dimension", dimension_state))

    logger.info(f"[子图-Map] 创建了 {len(sends)} 个并行任务")
    return sends


def reduce_analyses(state: AnalysisState) -> Dict[str, Any]:
    """
    Reduce 阶段：汇总所有维度的分析结果

    生成字典形式，每个维度的独立报告（用于部分状态传递）
    """
    logger.info(f"[子图-Reduce] 开始汇总 {len(state['analyses'])} 个维度的分析结果")

    # 整理分析结果为结构化格式
    analysis_reports_dict = {}

    for analysis in state["analyses"]:
        dimension_key = analysis['dimension_key']
        analysis_text = analysis['analysis_result']

        # 保存独立的维度报告（用于部分传输）
        analysis_reports_dict[dimension_key] = analysis_text

    logger.info(f"[子图-Reduce] 汇总完成，生成了 {len(analysis_reports_dict)} 个维度报告")
    return {
        "analysis_reports": analysis_reports_dict
    }


# ==========================================
# 最终报告生成节点
# ==========================================

def generate_final_report(state: AnalysisState) -> Dict[str, Any]:
    """
    生成最终的现状综合分析报告

    整合所有维度的分析结果，使用汇总 Prompt 生成连贯的报告。
    支持LangSmith tracing。
    """
    logger.info("[子图-汇总] 开始生成最终综合报告")

    try:
        # 使用 reduce 阶段生成的 dimension_reports_text
        dimension_reports_text = state.get("dimension_reports_text", "")

        # 如果 dimension_reports_text 为空，从 analyses 重新构建
        if not dimension_reports_text:
            for analysis in state["analyses"]:
                dimension_reports_text += f"\n### {analysis['dimension_name']}\n{analysis['analysis_result']}\n"

        # 构建汇总 Prompt
        summary_prompt = ANALYSIS_SUMMARY_PROMPT.format(
            dimension_reports=dimension_reports_text
        )

        # 调用 LLM 生成最终报告（支持LangSmith）
        from ..core.llm_factory import create_llm
        from ..core.langsmith_integration import get_langsmith_manager

        # 创建LangSmith metadata
        langsmith = get_langsmith_manager()
        metadata = None
        if langsmith.is_enabled():
            metadata = langsmith.create_run_metadata(
                project_name=state.get('project_name', '村庄'),
                dimension="analysis_summary",
                layer=1
            )

        llm = create_llm(
            model=LLM_MODEL,
            temperature=0.7,
            max_tokens=MAX_TOKENS,
            metadata=metadata
        )
        response = llm.invoke([HumanMessage(content=summary_prompt)])

        final_report = f"""# {state.get('project_name', '村庄')}现状综合分析报告

{response.content}
"""

        logger.info(f"[子图-汇总] 最终报告生成完成，共 {len(final_report)} 字符")

        return {
            "final_report": final_report,
            "messages": [AIMessage(content=final_report)]
        }

    except Exception as e:
        logger.error(f"[子图-汇总] 报告生成失败: {str(e)}")

        # 降级方案：直接拼接各维度结果
        fallback_report = f"""# {state.get('project_name', '村庄')}现状分析报告（简化版）

## 各维度分析

"""
        for analysis in state["analyses"]:
            fallback_report += f"### {analysis['dimension_name']}\n\n{analysis['analysis_result']}\n\n"

        return {
            "final_report": fallback_report,
            "messages": [AIMessage(content=fallback_report)]
        }


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
        "historical_culture"  # 历史文化分析
    ]

    logger.info(f"[子图-初始化] 设置 {len(all_dimensions)} 个分析维度")

    return {
        "subjects": all_dimensions,
        "analyses": []
    }


# ==========================================
# 构建子图
# ==========================================

def create_analysis_subgraph() -> StateGraph:
    """
    创建现状分析子图 - 使用封装节点

    Returns:
        编译后的 StateGraph 实例
    """
    from ..nodes.subgraph_nodes import (
        InitializeAnalysisNode,
        AnalyzeDimensionNode,
        ReduceAnalysesNode,
        GenerateAnalysisReportNode
    )

    logger.info("[子图构建] 开始构建现状分析子图（使用封装节点）")

    # 创建状态图
    builder = StateGraph(AnalysisState)

    # 创建节点实例
    initialize_node = InitializeAnalysisNode()
    analyze_node = AnalyzeDimensionNode()
    reduce_node = ReduceAnalysesNode()
    report_node = GenerateAnalysisReportNode()

    # 添加节点
    builder.add_node("initialize", initialize_node)
    builder.add_node("analyze_dimension", analyze_node)
    builder.add_node("reduce_analyses", reduce_node)
    # 注释掉综合报告生成节点，直接使用维度报告
    # builder.add_node("generate_report", report_node)

    # 构建执行流程
    builder.add_edge(START, "initialize")

    # 关键：使用条件边实现并行分发
    # 在 LangGraph 1.0.x 中，Send 对象必须由路由函数返回，不能由节点返回
    # 路由函数接收状态并返回 Send 对象列表
    def route_to_dimensions(state: AnalysisState) -> List[Send]:
        """路由函数：将状态分发到各维度的分析节点"""
        return map_dimensions(state)

    builder.add_conditional_edges("initialize", route_to_dimensions)

    builder.add_edge("analyze_dimension", "reduce_analyses")
    # 跳过综合报告生成，直接结束
    builder.add_edge("reduce_analyses", END)
    # builder.add_edge("reduce_analyses", "generate_report")
    # builder.add_edge("generate_report", END)

    # 编译子图
    analysis_subgraph = builder.compile()

    logger.info("[子图构建] 现状分析子图构建完成（使用封装节点）")

    return analysis_subgraph


# ==========================================
# 子图包装函数（用于父图调用）
# ==========================================

def call_analysis_subgraph(
    raw_data: str,
    project_name: str = "村庄"
) -> Dict[str, Any]:
    """
    调用现状分析子图的包装函数

    这个函数可以在父图中作为一个节点使用，实现"不同状态模式"的调用。

    Args:
        raw_data: 村庄原始数据
        project_name: 项目名称

    Returns:
        包含最终分析报告的字典
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
        "analysis_reports": {},
        "messages": []
    }

    try:
        # 调用子图
        result = subgraph.invoke(initial_state)

        # 使用维度报告作为主要输出
        analysis_reports = result.get("analysis_reports", {})
        
        logger.info(f"[子图调用] 子图执行成功，维度报告数量: {len(analysis_reports)}")

        return {
            "analysis_reports": analysis_reports,
            "success": True
        }

    except Exception as e:
        logger.error(f"[子图调用] 子图执行失败: {str(e)}")
        return {
            "analysis_reports": {},
            "success": False
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
        "analysis_reports": {},
        "messages": []
    }

    print("=== 开始执行现状分析子图 ===\n")

    result = subgraph.invoke(initial_state)

    print("\n=== 执行完成 ===")
    print(f"报告数: {len(result.get('analysis_reports', {}))} 个维度")
    print("\n=== 维度报告 ===")
    for key, value in result.get("analysis_reports", {}).items():
        print(f"- {key}: {len(value)} 字符")
