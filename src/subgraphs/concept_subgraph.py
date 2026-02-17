"""
规划思路子图 (Concept Subgraph)

基于现状分析，生成规划思路，包含4个维度的并行分析：
1. 资源禀赋分析
2. 规划定位分析
3. 发展目标分析
4. 规划策略分析

使用 LangGraph 的 Send 机制实现 Map-Reduce 模式。
支持部分状态传递优化，根据维度依赖关系筛选相关的现状分析信息。
"""

from typing import TypedDict, List, Dict, Any
from typing_extensions import Annotated
from langgraph.graph import StateGraph, END, START
from langgraph.types import Send
from langgraph.graph.message import add_messages
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage
import operator

from ..core.config import LLM_MODEL, MAX_TOKENS
from ..utils.logger import get_logger
from ..utils.state_filter import filter_analysis_report_for_concept
from .concept_prompts import (
    RESOURCE_ENDOWMENT_PROMPT,
    PLANNING_POSITIONING_PROMPT,
    DEVELOPMENT_GOALS_PROMPT,
    PLANNING_STRATEGIES_PROMPT,
    CONCEPT_SUMMARY_PROMPT,
    list_concept_dimensions
)

logger = get_logger(__name__)


# ==========================================
# 子图状态定义
# ==========================================

class ConceptState(TypedDict):
    """规划思路子图的状态"""
    # 输入数据
    analysis_report: str         # 现状分析报告（完整版，降级使用）
    dimension_reports: Dict[str, str]  # 各维度现状分析报告字典（用于部分状态传递）
    project_name: str            # 项目名称
    task_description: str         # 规划任务描述
    constraints: str             # 约束条件

    # 中间状态 - 用于并行分析
    dimensions: List[str]        # 待分析的维度列表
    concept_analyses: Annotated[List[Dict[str, str]], operator.add]  # 已完成的维度分析

    # 输出数据
    final_concept: str           # 最终规划思路报告
    concept_dimension_reports: Dict[str, str]  # 各维度独立报告（用于部分状态传递）

    # 消息历史
    messages: Annotated[List[BaseMessage], add_messages]


class ConceptDimensionState(TypedDict):
    """单个维度分析的状态（用于并行节点）"""
    dimension_key: str           # 维度标识
    dimension_name: str           # 维度名称
    analysis_report: str         # 现状分析报告（筛选后）
    dimension_reports: Dict[str, str]  # 完整的各维度现状分析字典（用于规划器二次筛选）
    task_description: str         # 规划任务
    constraints: str             # 约束条件
    concept_result: str          # 分析结果


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

def analyze_concept_dimension(state: ConceptDimensionState) -> Dict[str, Any]:
    """
    执行单个规划思路维度的分析

    使用 GenericPlanner 统一架构，充分利用现有的基础设施。

    Args:
        state: 包含维度信息和输入数据的状态

    Returns:
        该维度的分析结果（包装在列表中以支持 operator.add 累加）
    """
    dimension_key = state["dimension_key"]
    dimension_name = state["dimension_name"]

    logger.info(f"[子图-规划] 开始执行 {dimension_name} ({dimension_key})")

    try:
        # 【使用统一架构】使用 GenericPlannerFactory 创建规划器
        from ..planners.generic_planner import GenericPlannerFactory
        planner = GenericPlannerFactory.create_planner(dimension_key)

        # 【使用统一架构】调用规划器的 execute 方法
        # 注意：GenericPlanner 需要完整的状态字典，包含 analysis_report, task_description, constraints
        planner_state = {
            "analysis_report": state["analysis_report"],
            "dimension_reports": state.get("dimension_reports", {}),  # 可选，用于筛选
            "project_name": state.get("project_name", "村庄"),
            "task_description": state["task_description"],
            "constraints": state["constraints"]
        }
        planner_result = planner.execute(planner_state)

        # GenericPlanner 返回的结果键名由 get_result_key() 决定
        result_key = planner.get_result_key()
        concept_text = planner_result.get(result_key, planner_result.get("concept_result", ""))
        logger.info(f"[子图-规划] 完成 {dimension_name}，生成 {len(concept_text)} 字符")

        # 在 LangGraph 1.0.x 中，使用 operator.add 时需要返回列表
        return {
            "concept_analyses": [{
                "dimension_key": dimension_key,
                "dimension_name": dimension_name,
                "concept_result": concept_text
            }]
        }

    except Exception as e:
        logger.error(f"[子图-规划] {dimension_name} 执行失败: {str(e)}")
        # 返回错误信息而非崩溃
        return {
            "concept_analyses": [{
                "dimension_key": dimension_key,
                "dimension_name": dimension_name,
                "concept_result": f"[分析失败] {str(e)}"
            }]
        }


def _get_dimension_prompt(
    dimension_key: str,
    analysis_report: str,
    task_description: str,
    constraints: str
) -> str:
    """获取指定维度的 Prompt 模板"""
    prompts_map = {
        "resource_endowment": RESOURCE_ENDOWMENT_PROMPT,
        "planning_positioning": PLANNING_POSITIONING_PROMPT,
        "development_goals": DEVELOPMENT_GOALS_PROMPT,
        "planning_strategies": PLANNING_STRATEGIES_PROMPT,
    }

    if dimension_key not in prompts_map:
        raise ValueError(f"未知的规划维度: {dimension_key}")

    prompt_template = prompts_map[dimension_key]
    return prompt_template.format(
        project_name="",  # 可以从 state 中获取
        analysis_report=analysis_report[:3000],  # 限制长度
        task_description=task_description,
        constraints=constraints
    )


# ==========================================
# Map-Reduce 路由与分发节点
# ==========================================

def map_concept_dimensions(state: ConceptState) -> List[Send]:
    """
    Map 阶段：将4个维度映射为独立的分析任务

    使用 LangGraph 的 Send 机制，为每个维度创建独立的执行分支。
    每个维度只接收相关的现状分析信息（部分状态传递优化）。

    Returns:
        Send 对象列表，每个 Send 指向 analyze_concept_dimension 节点并携带独立状态
    """
    logger.info(f"[子图-Map] 开始分发 {len(state['dimensions'])} 个规划维度")

    # 获取完整的维度分析报告字典
    full_dimension_reports = state.get("dimension_reports", {})
    full_analysis_report = state.get("analysis_report", "")

    # 为每个维度创建 Send 对象
    sends = []
    for dimension_key in state["dimensions"]:
        # 获取维度信息
        dimensions_info = {d["key"]: d for d in list_concept_dimensions()}
        dimension_info = dimensions_info.get(dimension_key, {"name": dimension_key})

        # 【关键优化】筛选相关的现状分析
        filtered_analysis = filter_analysis_report_for_concept(
            concept_dimension=dimension_key,
            full_analysis_reports=full_dimension_reports,
            full_analysis_report=full_analysis_report
        )

        # 创建该维度的独立状态（使用筛选后的报告）
        dimension_state = {
            "dimension_key": dimension_key,
            "dimension_name": dimension_info["name"],
            "analysis_report": filtered_analysis,  # 筛选后的报告（已优化）
            "dimension_reports": full_dimension_reports,  # 完整字典（用于规划器二次筛选）
            "task_description": state["task_description"],
            "constraints": state["constraints"],
            "concept_result": ""
        }

        # 创建 Send 对象：发送到 analyze_concept_dimension 节点
        sends.append(Send("analyze_concept_dimension", dimension_state))

    logger.info(f"[子图-Map] 创建了 {len(sends)} 个并行任务（已优化状态传递）")
    return sends


def reduce_concept_analyses(state: ConceptState) -> Dict[str, Any]:
    """
    Reduce 阶段：汇总所有维度的分析结果

    生成两种格式：
    1. concept_dimension_reports: 字典形式，每个维度的独立报告（用于部分状态传递）
    2. dimension_reports_text: 拼接的文本（用于综合报告生成）
    """
    logger.info(f"[子图-Reduce] 开始汇总 {len(state['concept_analyses'])} 个维度的分析结果")

    # 整理分析结果为结构化格式
    dimension_reports_dict = {}
    dimension_reports_text = []

    for analysis in state["concept_analyses"]:
        dimension_key = analysis['dimension_key']
        dimension_name = analysis['dimension_name']
        concept_text = analysis['concept_result']

        # 保存独立的维度报告（用于部分传输）
        dimension_reports_dict[dimension_key] = concept_text

        # 同时拼接用于综合报告
        dimension_reports_text.append(f"""
## {dimension_name}

{concept_text}
---
""")

    logger.info(f"[子图-Reduce] 汇总完成，生成了 {len(dimension_reports_dict)} 个维度报告")
    return {
        "concept_dimension_reports": dimension_reports_dict,  # 新增：字典形式
        "dimension_reports_text": "\n".join(dimension_reports_text)  # 用于综合报告
    }


# ==========================================
# 最终规划思路生成节点
# ==========================================

def generate_final_concept(state: ConceptState) -> Dict[str, Any]:
    """
    生成最终规划思路报告

    整合4个维度的分析结果，使用汇总 Prompt 生成连贯的报告。
    支持LangSmith tracing。
    """
    logger.info("[子图-汇总] 开始生成最终规划思路报告")

    try:
        # 使用 reduce 阶段生成的 dimension_reports_text
        dimension_reports_text = state.get("dimension_reports_text", "")

        # 如果 dimension_reports_text 为空，从 concept_analyses 重新构建
        if not dimension_reports_text:
            for analysis in state["concept_analyses"]:
                dimension_reports_text += f"\n### {analysis['dimension_name']}\n{analysis['concept_result']}\n"

        # 构建汇总 Prompt
        summary_prompt = CONCEPT_SUMMARY_PROMPT.format(
            project_name=state["project_name"],
            task_description=state["task_description"],
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
                dimension="concept_summary",
                layer=2
            )

        llm = create_llm(
            model=LLM_MODEL,
            temperature=0.7,
            max_tokens=MAX_TOKENS,
            metadata=metadata
        )
        response = llm.invoke([HumanMessage(content=summary_prompt)])

        final_concept = f"""# {state['project_name']} 规划思路报告

{response.content}
---

**生成时间**: {__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""

        logger.info(f"[子图-汇总] 规划思路报告生成完成，共 {len(final_concept)} 字符")

        return {
            "final_concept": final_concept,
            "messages": [AIMessage(content=final_concept)]
        }

    except Exception as e:
        logger.error(f"[子图-汇总] 报告生成失败: {str(e)}")

        # 降级方案：直接拼接各维度结果
        fallback_concept = f"""# {state['project_name']} 规划思路报告（简化版）

## 各维度分析

"""
        for analysis in state["concept_analyses"]:
            fallback_concept += f"### {analysis['dimension_name']}\n\n{analysis['concept_result']}\n\n"

        return {
            "final_concept": fallback_concept,
            "messages": [AIMessage(content=fallback_concept)]
        }


# ==========================================
# 初始化节点
# ==========================================

def initialize_concept_analysis(state: ConceptState) -> Dict[str, Any]:
    """
    初始化规划思路分析流程，设置待分析的维度列表
    """
    logger.info(f"[子图-初始化] 开始规划思路分析，项目: {state.get('project_name', '未命名')}")

    # 定义4个规划维度
    all_dimensions = [
        "resource_endowment",   # 资源禀赋
        "planning_positioning",  # 规划定位
        "development_goals",     # 发展目标
        "planning_strategies"    # 规划策略
    ]

    logger.info(f"[子图-初始化] 设置 {len(all_dimensions)} 个规划维度")

    return {
        "dimensions": all_dimensions,
        "concept_analyses": []
    }


# ==========================================
# 构建子图
# ==========================================

def create_concept_subgraph() -> StateGraph:
    """
    创建规划思路子图 - 使用封装节点

    Returns:
        编译后的 StateGraph 实例
    """
    from ..nodes.subgraph_nodes import (
        InitializeConceptNode,
        AnalyzeConceptDimensionNode,
        ReduceConceptsNode,
        GenerateConceptReportNode
    )

    logger.info("[子图构建] 开始构建规划思路子图（使用封装节点）")

    # 创建状态图
    builder = StateGraph(ConceptState)

    # 创建节点实例
    initialize_node = InitializeConceptNode()
    analyze_node = AnalyzeConceptDimensionNode()
    reduce_node = ReduceConceptsNode()
    report_node = GenerateConceptReportNode()

    # 添加节点
    builder.add_node("initialize", initialize_node)
    builder.add_node("analyze_concept_dimension", analyze_node)
    builder.add_node("reduce_analyses", reduce_node)
    builder.add_node("generate_final_concept", report_node)

    # 构建执行流程
    builder.add_edge(START, "initialize")

    # 关键：使用条件边实现并行分发
    # 在 LangGraph 1.0.x 中，Send 对象必须由路由函数返回，不能由节点返回
    # 路由函数接收状态并返回 Send 对象列表
    def route_to_concept_dimensions(state: ConceptState) -> List[Send]:
        """路由函数：将状态分发到各维度的规划思路节点"""
        return map_concept_dimensions(state)

    builder.add_conditional_edges("initialize", route_to_concept_dimensions)

    builder.add_edge("analyze_concept_dimension", "reduce_analyses")
    builder.add_edge("reduce_analyses", "generate_final_concept")
    builder.add_edge("generate_final_concept", END)

    # 编译子图
    concept_subgraph = builder.compile()

    logger.info("[子图构建] 规划思路子图构建完成（使用封装节点）")

    return concept_subgraph


# ==========================================
# 子图包装函数（用于父图调用）
# ==========================================

def call_concept_subgraph(
    project_name: str,
    analysis_report: str,
    dimension_reports: Dict[str, str] = None,  # 新增：维度报告字典
    task_description: str = "制定村庄总体规划思路",
    constraints: str = "无特殊约束"
) -> Dict[str, Any]:
    """
    调用规划思路子图的包装函数

    Args:
        project_name: 项目/村庄名称
        analysis_report: 现状分析报告（完整版）
        dimension_reports: 各维度现状分析报告字典（用于部分状态传递）
        task_description: 规划任务描述
        constraints: 约束条件

    Returns:
        包含最终规划思路报告的字典
    """
    logger.info(f"[子图调用] 开始调用规划思路子图: {project_name}")

    # 创建子图实例
    subgraph = create_concept_subgraph()

    # 构建初始状态
    initial_state: ConceptState = {
        "analysis_report": analysis_report,
        "dimension_reports": dimension_reports or {},  # 新增
        "project_name": project_name,
        "task_description": task_description,
        "constraints": constraints,
        "dimensions": [],
        "concept_analyses": [],
        "final_concept": "",
        "concept_dimension_reports": {},  # 新增
        "messages": []
    }

    try:
        # 调用子图
        result = subgraph.invoke(initial_state)

        logger.info(f"[子图调用] 子图执行成功，报告长度: {len(result.get('final_concept', ''))} 字符")
        logger.info(f"[子图调用] 维度报告数量: {len(result.get('concept_dimension_reports', {}))}")

        return {
            "concept_report": result["final_concept"],
            "concept_dimension_reports": result.get("concept_dimension_reports", {}),  # 新增
            "success": True
        }

    except Exception as e:
        logger.error(f"[子图调用] 子图执行失败: {str(e)}")
        return {
            "concept_report": f"规划思路分析失败: {str(e)}",
            "concept_dimension_reports": {},  # 新增：失败时返回空字典
            "success": False
        }


# ==========================================
# 测试入口
# ==========================================

if __name__ == "__main__":
    # 测试数据
    test_analysis = """
    # 某某村现状分析报告

    区位分析：位于XX市XX区，距离市中心25公里，交通便利。
    社会经济：人口1200人，主要产业为农业和旅游业。
    自然环境：丘陵地貌，森林覆盖率68%。
    """

    # 创建并运行子图
    subgraph = create_concept_subgraph()

    initial_state = {
        "analysis_report": test_analysis,
        "dimension_reports": {},
        "project_name": "测试村",
        "task_description": "制定乡村振兴规划思路",
        "constraints": "生态优先，绿色发展",
        "dimensions": [],
        "concept_analyses": [],
        "final_concept": "",
        "concept_dimension_reports": {},
        "messages": []
    }

    print("=== 开始执行规划思路子图 ===\n")

    result = subgraph.invoke(initial_state)

    print("\n=== 执行完成 ===")
    print(f"报告长度: {len(result['final_concept'])} 字符")
    print("\n=== 最终规划思路 ===")
    print(result["final_concept"])
