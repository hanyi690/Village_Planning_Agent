"""
规划思路子图 (Concept Subgraph)

基于现状分析，生成规划思路，包含4个维度的并行分析：
1. 资源禀赋分析
2. 规划定位分析
3. 发展目标分析
4. 规划策略分析

使用 LangGraph 的 Send 机制实现 Map-Reduce 模式。
"""

from typing import TypedDict, List, Dict, Any
from typing_extensions import Annotated
from langgraph.graph import StateGraph, END, START, Send
from langgraph.graph.message import add_messages
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage
import operator

from ..core.config import LLM_MODEL, MAX_TOKENS
from ..utils.logger import get_logger
from .prompts import (
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
    analysis_report: str         # 现状分析报告
    project_name: str            # 项目名称
    task_description: str         # 规划任务描述
    constraints: str             # 约束条件

    # 中间状态 - 用于并行分析
    dimensions: List[str]        # 待分析的维度列表
    concept_analyses: Annotated[List[Dict[str, str]], operator.add]  # 已完成的维度分析

    # 输出数据
    final_concept: str           # 最终规划思路报告

    # 消息历史
    messages: Annotated[List[BaseMessage], add_messages]


class ConceptDimensionState(TypedDict):
    """单个维度分析的状态（用于并行节点）"""
    dimension_key: str           # 维度标识
    dimension_name: str           # 维度名称
    analysis_report: str         # 现状分析报告
    task_description: str         # 规划任务
    constraints: str             # 约束条件
    concept_result: str          # 分析结果


# ==========================================
# LLM 调用辅助函数
# ==========================================

def _get_llm():
    """延迟导入 LLM"""
    from langchain.chat_models import ChatOpenAI
    return ChatOpenAI(model=LLM_MODEL, temperature=0.7, max_tokens=MAX_TOKENS)


# ==========================================
# 并行分析节点函数
# ==========================================

def analyze_concept_dimension(state: ConceptDimensionState) -> Dict[str, Any]:
    """
    执行单个规划思路维度的分析

    Args:
        state: 包含维度信息和输入数据的状态

    Returns:
        该维度的分析结果
    """
    dimension_key = state["dimension_key"]
    dimension_name = state["dimension_name"]
    analysis_report = state["analysis_report"]
    task_description = state["task_description"]
    constraints = state["constraints"]

    logger.info(f"[子图-规划] 开始执行 {dimension_name} ({dimension_key})")

    try:
        # 获取该维度的 Prompt
        prompt = _get_dimension_prompt(
            dimension_key,
            analysis_report,
            task_description,
            constraints
        )

        # 调用 LLM
        llm = _get_llm()
        response = llm.invoke([HumanMessage(content=prompt)])

        concept_text = response.content
        logger.info(f"[子图-规划] 完成 {dimension_name}，生成 {len(concept_text)} 字符")

        return {
            "dimension_key": dimension_key,
            "dimension_name": dimension_name,
            "concept_result": concept_text
        }

    except Exception as e:
        logger.error(f"[子图-规划] {dimension_name} 执行失败: {str(e)}")
        return {
            "dimension_key": dimension_key,
            "dimension_name": dimension_name,
            "concept_result": f"[分析失败] {str(e)}"
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

    Returns:
        Send 对象列表，每个 Send 指向 analyze_concept_dimension 节点并携带独立状态
    """
    logger.info(f"[子图-Map] 开始分发 {len(state['dimensions'])} 个规划维度")

    # 为每个维度创建 Send 对象
    sends = []
    for dimension_key in state["dimensions"]:
        # 获取维度信息
        dimensions_info = {d["key"]: d for d in list_concept_dimensions()}
        dimension_info = dimensions_info.get(dimension_key, {"name": dimension_key})

        # 创建该维度的独立状态
        dimension_state = {
            "dimension_key": dimension_key,
            "dimension_name": dimension_info["name"],
            "analysis_report": state["analysis_report"],
            "task_description": state["task_description"],
            "constraints": state["constraints"],
            "concept_result": ""
        }

        # 创建 Send 对象：发送到 analyze_concept_dimension 节点
        sends.append(Send("analyze_concept_dimension", dimension_state))

    logger.info(f"[子图-Map] 创建了 {len(sends)} 个并行任务")
    return sends


def reduce_concept_analyses(state: ConceptState) -> Dict[str, Any]:
    """
    Reduce 阶段：汇总所有维度的分析结果
    """
    logger.info(f"[子图-Reduce] 开始汇总 {len(state['concept_analyses'])} 个维度的分析结果")

    # 整理分析结果为结构化格式
    dimension_reports = []
    for analysis in state["concept_analyses"]:
        dimension_reports.append(f"""
## {analysis['dimension_name']}

{analysis['concept_result']}
---
""")

    logger.info("[子图-Reduce] 汇总完成，准备生成最终规划思路")
    return {
        "dimension_reports": "\n".join(dimension_reports)
    }


# ==========================================
# 最终规划思路生成节点
# ==========================================

def generate_final_concept(state: ConceptState) -> Dict[str, Any]:
    """
    生成最终规划思路报告

    整合4个维度的分析结果，使用汇总 Prompt 生成连贯的报告。
    """
    logger.info("[子图-汇总] 开始生成最终规划思路报告")

    try:
        # 整理各维度分析为文本
        dimension_reports_text = ""
        for analysis in state["concept_analyses"]:
            dimension_reports_text += f"\n### {analysis['dimension_name']}\n{analysis['concept_result']}\n"

        # 构建汇总 Prompt
        summary_prompt = CONCEPT_SUMMARY_PROMPT.format(
            project_name=state["project_name"],
            task_description=state["task_description"],
            dimension_reports=dimension_reports_text
        )

        # 调用 LLM 生成最终报告
        llm = _get_llm()
        response = llm.invoke([
            HumanMessage(content=summary_prompt)
        ])

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
    创建规划思路子图

    Returns:
        编译后的 StateGraph 实例
    """
    logger.info("[子图构建] 开始构建规划思路子图")

    # 创建状态图
    builder = StateGraph(ConceptState)

    # 添加节点
    builder.add_node("initialize", initialize_concept_analysis)
    builder.add_node("map_dimensions", map_concept_dimensions)
    builder.add_node("analyze_concept_dimension", analyze_concept_dimension)
    builder.add_node("reduce_analyses", reduce_concept_analyses)
    builder.add_node("generate_final_concept", generate_final_concept)

    # 构建执行流程
    builder.add_edge(START, "initialize")
    builder.add_edge("initialize", "map_dimensions")

    # 关键：使用条件边实现并行分发
    builder.add_conditional_edges(
        "map_dimensions",
        map_concept_dimensions,
        ["analyze_concept_dimension"]
    )

    builder.add_edge("analyze_concept_dimension", "reduce_analyses")
    builder.add_edge("reduce_analyses", "generate_final_concept")
    builder.add_edge("generate_final_concept", END)

    # 编译子图
    concept_subgraph = builder.compile()

    logger.info("[子图构建] 规划思路子图构建完成")

    return concept_subgraph


# ==========================================
# 子图包装函数（用于父图调用）
# ==========================================

def call_concept_subgraph(
    project_name: str,
    analysis_report: str,
    task_description: str = "制定村庄总体规划思路",
    constraints: str = "无特殊约束"
) -> Dict[str, Any]:
    """
    调用规划思路子图的包装函数

    Args:
        project_name: 项目/村庄名称
        analysis_report: 现状分析报告
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
        "project_name": project_name,
        "task_description": task_description,
        "constraints": constraints,
        "dimensions": [],
        "concept_analyses": [],
        "final_concept": "",
        "messages": []
    }

    try:
        # 调用子图
        result = subgraph.invoke(initial_state)

        logger.info(f"[子图调用] 子图执行成功，报告长度: {len(result.get('final_concept', ''))} 字符")

        return {
            "concept_report": result["final_concept"],
            "success": True
        }

    except Exception as e:
        logger.error(f"[子图调用] 子图执行失败: {str(e)}")
        return {
            "concept_report": f"规划思路分析失败: {str(e)}",
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
        "project_name": "测试村",
        "task_description": "制定乡村振兴规划思路",
        "constraints": "生态优先，绿色发展",
        "dimensions": [],
        "concept_analyses": [],
        "final_concept": "",
        "messages": []
    }

    print("=== 开始执行规划思路子图 ===\n")

    result = subgraph.invoke(initial_state)

    print("\n=== 执行完成 ===")
    print(f"报告长度: {len(result['final_concept'])} 字符")
    print("\n=== 最终规划思路 ===")
    print(result["final_concept"])
