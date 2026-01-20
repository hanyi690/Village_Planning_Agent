"""
村庄规划主图 (Main Graph)

管理三层规划流程的执行：
1. Layer 1: 现状分析（使用现状分析子图）
2. Layer 2: 规划思路生成
3. Layer 3: 详细规划（待实现）

支持人工审核和反馈循环。
"""

from typing import TypedDict, List, Dict, Any, Literal
from typing_extensions import Annotated
from langgraph.graph import StateGraph, END, START
from langgraph.graph.message import add_messages
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage
import operator

from .core.config import LLM_MODEL, MAX_TOKENS
from .core.prompts import SYSTEM_PROMPT, PLANNING_CONCEPT_PROMPT
from .utils.logger import get_logger
from .subgraphs.analysis_subgraph import call_analysis_subgraph
from .subgraphs.concept_subgraph import call_concept_subgraph
from .subgraphs.detailed_plan_subgraph import call_detailed_plan_subgraph

logger = get_logger(__name__)


# ==========================================
# 主图状态定义
# ==========================================

class VillagePlanningState(TypedDict):
    """村庄规划主图的状态"""
    # 输入
    project_name: str              # 项目/村庄名称
    village_data: str              # 村庄基础数据
    task_description: str          # 规划任务描述
    constraints: str               # 约束条件

    # 流程控制
    current_layer: int             # 当前执行层级 (1/2/3)
    layer_1_completed: bool        # 现状分析完成
    layer_2_completed: bool        # 规划思路完成
    layer_3_completed: bool        # 详细规划完成

    # 人工审核
    need_human_review: bool        # 是否需要人工审核
    human_feedback: str            # 人工反馈

    # 各层成果
    analysis_report: str           # 现状分析报告
    dimension_reports: Dict[str, str]  # 各维度现状分析报告（用于部分状态传递）
    planning_concept: str          # 规划思路
    concept_dimension_reports: Dict[str, str]  # 各维度规划思路报告（用于部分状态传递）
    detailed_plan: str             # 详细规划方案
    final_output: str              # 最终成果

    # 消息历史
    messages: Annotated[List[BaseMessage], add_messages]


# ==========================================
# LLM 辅助函数
# ==========================================

def _get_llm():
    """获取 LLM 实例，使用统一的 LLM 工厂"""
    from .core.llm_factory import create_llm
    return create_llm(model=LLM_MODEL, temperature=0.7, max_tokens=MAX_TOKENS)


# ==========================================
# Layer 1: 现状分析
# ==========================================

def execute_layer1_analysis(state: VillagePlanningState) -> Dict[str, Any]:
    """
    Layer 1: 执行现状分析

    调用现状分析子图进行10个维度的并行分析。
    """
    logger.info(f"[主图-Layer1] 开始现状分析，项目: {state['project_name']}")

    try:
        # 调用现状分析子图
        result = call_analysis_subgraph(
            raw_data=state["village_data"],
            project_name=state["project_name"]
        )

        if result["success"]:
            logger.info(f"[主图-Layer1] 现状分析完成，报告长度: {len(result['analysis_report'])} 字符")
            return {
                "analysis_report": result["analysis_report"],
                "dimension_reports": result.get("dimension_reports", {}),  # 新增：传递维度报告
                "layer_1_completed": True,
                "current_layer": 2,
                "messages": [AIMessage(content=f"现状分析完成，生成了 {len(result['analysis_report'])} 字符的综合报告。")]
            }
        else:
            logger.error(f"[主图-Layer1] 现状分析失败: {result['analysis_report']}")
            return {
                "analysis_report": f"现状分析失败: {result['analysis_report']}",
                "dimension_reports": {},  # 新增：失败时返回空字典
                "layer_1_completed": False,
                "messages": [AIMessage(content="现状分析失败，请检查输入数据或稍后重试。")]
            }

    except Exception as e:
        logger.error(f"[主图-Layer1] 执行异常: {str(e)}")
        return {
            "analysis_report": f"执行异常: {str(e)}",
            "dimension_reports": {},  # 新增：异常时返回空字典
            "layer_1_completed": False,
            "messages": [AIMessage(content=f"现状分析过程中发生错误: {str(e)}")]
        }


# ==========================================
# Layer 2: 规划思路生成
# ==========================================

def execute_layer2_concept(state: VillagePlanningState) -> Dict[str, Any]:
    """
    Layer 2: 生成规划思路（使用规划思路子图）

    调用规划思路子图进行4个维度的并行分析。
    """
    logger.info(f"[主图-Layer2] 开始规划思路分析，项目: {state['project_name']}")

    try:
        # 调用规划思路子图（传递维度报告字典）
        result = call_concept_subgraph(
            project_name=state["project_name"],
            analysis_report=state["analysis_report"],
            dimension_reports=state.get("dimension_reports", {}),  # 新增：传递维度报告
            task_description=state["task_description"],
            constraints=state.get("constraints", "无特殊约束")
        )

        if result["success"]:
            logger.info(f"[主图-Layer2] 规划思路完成，报告长度: {len(result['concept_report'])} 字符")
            return {
                "planning_concept": result["concept_report"],
                "concept_dimension_reports": result.get("concept_dimension_reports", {}),  # 新增：传递规划维度报告
                "layer_2_completed": True,
                "current_layer": 3,
                "messages": [AIMessage(content=f"规划思路已生成，长度 {len(result['concept_report'])} 字符。")]
            }
        else:
            logger.error(f"[主图-Layer2] 规划思路失败: {result['concept_report']}")
            return {
                "planning_concept": f"规划思路失败: {result['concept_report']}",
                "concept_dimension_reports": {},  # 新增：失败时返回空字典
                "layer_2_completed": False,
                "messages": [AIMessage(content="规划思路生成失败，请检查输入数据或稍后重试。")]
            }

    except Exception as e:
        logger.error(f"[主图-Layer2] 执行异常: {str(e)}")
        return {
            "planning_concept": f"执行异常: {str(e)}",
            "concept_dimension_reports": {},  # 新增：异常时返回空字典
            "layer_2_completed": False,
            "messages": [AIMessage(content=f"规划思路生成过程中发生错误: {str(e)}")]
        }


# ==========================================
# Layer 3: 详细规划（占位符）
# ==========================================

def execute_layer3_detail(state: VillagePlanningState) -> Dict[str, Any]:
    """
    Layer 3: 详细规划

    调用详细规划子图进行10个专业维度的规划。
    """
    logger.info(f"[主图-Layer3] 开始生成详细规划，项目: {state['project_name']}")

    try:
        # 调用详细规划子图（传递维度报告字典）
        result = call_detailed_plan_subgraph(
            project_name=state["project_name"],
            analysis_report=state["analysis_report"],
            planning_concept=state["planning_concept"],
            dimension_reports=state.get("dimension_reports", {}),  # 新增：传递维度报告
            concept_dimension_reports=state.get("concept_dimension_reports", {}),  # 新增：传递规划维度报告
            task_description=state.get("task_description", "制定村庄详细规划"),
            constraints=state.get("constraints", "无特殊约束"),
            required_dimensions=state.get("required_dimensions"),  # 可选：指定维度
            enable_human_review=state.get("need_human_review", False)
        )

        if result["success"]:
            logger.info(f"[主图-Layer3] 详细规划完成，报告长度: {len(result['detailed_plan_report'])} 字符")
            logger.info(f"[主图-Layer3] 已完成维度: {result['completed_dimensions']}")

            return {
                "detailed_plan": result["detailed_plan_report"],
                "layer_3_completed": True,
                "current_layer": 4,
                "messages": [AIMessage(content=f"详细规划已生成，包含 {len(result['completed_dimensions'])} 个专业维度。")]
            }
        else:
            logger.error(f"[主图-Layer3] 详细规划失败: {result.get('error', '未知错误')}")
            return {
                "detailed_plan": f"详细规划失败: {result.get('error', '未知错误')}",
                "layer_3_completed": False,
                "messages": [AIMessage(content="详细规划生成失败，请检查输入数据或稍后重试。")]
            }

    except Exception as e:
        logger.error(f"[主图-Layer3] 执行异常: {str(e)}")
        return {
            "detailed_plan": f"执行异常: {str(e)}",
            "layer_3_completed": False,
            "messages": [AIMessage(content=f"详细规划过程中发生错误: {str(e)}")]
        }


# ==========================================
# 最终成果生成
# ==========================================

def generate_final_output(state: VillagePlanningState) -> Dict[str, Any]:
    """
    生成最终规划成果

    整合三层输出，生成完整的规划文档。
    """
    logger.info(f"[主图-成果] 开始生成最终成果，项目: {state['project_name']}")

    final_output = f"""
# {state['project_name']} 村庄规划成果

---

## 一、现状分析报告

{state['analysis_report']}

---

## 二、规划思路

{state['planning_concept']}

---

## 三、详细规划方案

{state['detailed_plan']}

---

**生成时间**: {__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

**说明**: 本成果由 AI 村庄规划系统生成，仅供参考。实际规划需结合专业评估和审批流程。
"""

    logger.info(f"[主图-成果] 最终成果生成完成，总长度: {len(final_output)} 字符")

    return {
        "final_output": final_output,
        "messages": [AIMessage(content="最终规划成果已生成！")]
    }


# ==========================================
# 条件路由与审核
# ==========================================

def route_after_layer1(state: VillagePlanningState) -> Literal["human_review", "layer2", "end"]:
    """
    Layer 1 完成后的路由决策
    """
    if not state["layer_1_completed"]:
        # 分析失败，结束
        logger.warning("[主图-路由] 现状分析失败，流程终止")
        return "end"

    if state.get("need_human_review", False):
        # 需要人工审核
        logger.info("[主图-路由] 进入人工审核环节")
        return "human_review"

    # 直接进入 Layer 2
    logger.info("[主图-路由] 直接进入规划思路阶段")
    return "layer2"


def route_after_layer2(state: VillagePlanningState) -> Literal["human_review", "layer3", "end"]:
    """
    Layer 2 完成后的路由决策
    """
    if not state["layer_2_completed"]:
        logger.warning("[主图-路由] 规划思路生成失败，流程终止")
        return "end"

    if state.get("need_human_review", False):
        logger.info("[主图-路由] 进入人工审核环节")
        return "human_review"

    logger.info("[主图-路由] 进入详细规划阶段")
    return "layer3"


def route_after_layer3(state: VillagePlanningState) -> Literal["final", "end"]:
    """
    Layer 3 完成后的路由决策
    """
    if state["layer_3_completed"]:
        logger.info("[主图-路由] 进入最终成果生成")
        return "final"
    else:
        logger.warning("[主图-路由] 详细规划失败，流程终止")
        return "end"


def human_review_node(state: VillagePlanningState) -> Dict[str, Any]:
    """
    人工审核节点

    在实际应用中，这里应该：
    1. 暂停执行，等待人工输入
    2. 支持修改反馈
    3. 根据反馈决定：通过/驳回/终止

    当前版本：简化处理，直接通过
    """
    logger.info(f"[主图-人工审核] 等待人工审核（当前版本自动通过）")

    feedback = state.get("human_feedback", "")
    if feedback:
        logger.info(f"[主图-人工审核] 收到反馈: {feedback}")

    # 当前版本：自动通过
    return {
        "messages": [AIMessage(content="人工审核完成（当前版本自动通过）")],
        "need_human_review": False
    }


# ==========================================
# 构建主图
# ==========================================

def create_village_planning_graph() -> StateGraph:
    """
    创建村庄规划主图

    Returns:
        编译后的 StateGraph 实例
    """
    logger.info("[主图构建] 开始构建村庄规划主图")

    builder = StateGraph(VillagePlanningState)

    # 添加节点
    builder.add_node("layer1_analysis", execute_layer1_analysis)
    builder.add_node("layer2_concept", execute_layer2_concept)
    builder.add_node("layer3_detail", execute_layer3_detail)
    builder.add_node("generate_final", generate_final_output)
    builder.add_node("human_review", human_review_node)

    # 构建执行流程
    builder.add_edge(START, "layer1_analysis")

    # Layer 1 -> 审核/layer2/end
    builder.add_conditional_edges(
        "layer1_analysis",
        route_after_layer1,
        {
            "human_review": "human_review",
            "layer2": "layer2_concept",
            "end": END
        }
    )

    # 人工审核 -> layer2
    builder.add_edge("human_review", "layer2_concept")

    # Layer 2 -> 审核/layer3/end
    builder.add_conditional_edges(
        "layer2_concept",
        route_after_layer2,
        {
            "human_review": "human_review",
            "layer3": "layer3_detail",
            "end": END
        }
    )

    # Layer 3 -> final/end
    builder.add_conditional_edges(
        "layer3_detail",
        route_after_layer3,
        {
            "final": "generate_final",
            "end": END
        }
    )

    # 最终节点 -> END
    builder.add_edge("generate_final", END)

    # 编译主图
    main_graph = builder.compile()

    logger.info("[主图构建] 村庄规划主图构建完成")

    return main_graph


# ==========================================
# 对外接口
# ==========================================

def run_village_planning(
    project_name: str,
    village_data: str,
    task_description: str = "制定村庄总体规划方案",
    constraints: str = "无特殊约束",
    need_human_review: bool = False,
    stream_mode: bool = False
) -> Dict[str, Any]:
    """
    执行村庄规划主流程

    Args:
        project_name: 项目/村庄名称
        village_data: 村庄基础数据
        task_description: 规划任务描述
        constraints: 约束条件
        need_human_review: 是否需要人工审核
        stream_mode: 是否使用流式输出

    Returns:
        包含最终成果的字典
    """
    logger.info(f"[主图-调用] 开始执行村庄规划: {project_name}")

    # 创建主图
    graph = create_village_planning_graph()

    # 初始状态
    initial_state = {
        "project_name": project_name,
        "village_data": village_data,
        "task_description": task_description,
        "constraints": constraints,
        "current_layer": 1,
        "layer_1_completed": False,
        "layer_2_completed": False,
        "layer_3_completed": False,
        "need_human_review": need_human_review,
        "human_feedback": "",
        "analysis_report": "",
        "dimension_reports": {},  # 新增：初始化维度报告字典
        "planning_concept": "",
        "concept_dimension_reports": {},  # 新增：初始化规划维度字典
        "detailed_plan": "",
        "final_output": "",
        "messages": []
    }

    try:
        if stream_mode:
            # 流式执行
            logger.info("[主图-调用] 使用流式模式")
            events = []
            for event in graph.stream(initial_state, stream_mode="values"):
                events.append(event)
                # 打印进度
                if "messages" in event and event["messages"]:
                    latest_msg = event["messages"][-1]
                    if hasattr(latest_msg, 'content'):
                        print(f"[进度] {latest_msg.content[:100]}...")

            final_state = events[-1] if events else initial_state
        else:
            # 一次性执行
            final_state = graph.invoke(initial_state)

        logger.info("[主图-调用] 规划流程执行完成")

        return {
            "success": True,
            "final_output": final_state.get("final_output", ""),
            "analysis_report": final_state.get("analysis_report", ""),
            "planning_concept": final_state.get("planning_concept", ""),
            "detailed_plan": final_state.get("detailed_plan", ""),
            "all_layers_completed": all([
                final_state.get("layer_1_completed", False),
                final_state.get("layer_2_completed", False),
                final_state.get("layer_3_completed", False)
            ])
        }

    except Exception as e:
        logger.error(f"[主图-调用] 执行失败: {str(e)}")
        return {
            "success": False,
            "error": str(e),
            "final_output": f"执行失败: {str(e)}"
        }


# ==========================================
# 测试入口
# ==========================================

if __name__ == "__main__":
    # 测试数据
    test_data = """
    # 测试村庄基础数据
    - 村庄名称：测试村
    - 人口：1200人
    - 面积：5.2平方公里
    - 主要产业：农业、旅游业
    """

    print("=== 开始测试村庄规划主图 ===\n")

    result = run_village_planning(
        project_name="测试村",
        village_data=test_data,
        task_description="制定乡村振兴总体规划",
        constraints="注重生态环境保护，传承历史文化"
    )

    print("\n=== 执行完成 ===")
    print(f"成功: {result['success']}")
    print(f"所有层级完成: {result.get('all_layers_completed', False)}")
    print(f"最终成果长度: {len(result['final_output'])} 字符")

    if result['success']:
        print("\n=== 最终成果预览（前1500字符）===")
        print(result['final_output'][:1500])
