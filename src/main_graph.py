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
from pathlib import Path
from langgraph.graph import StateGraph, END, START
from langgraph.graph.message import add_messages
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage
import operator

from .core.config import LLM_MODEL, MAX_TOKENS
from .core.prompts import SYSTEM_PROMPT, PLANNING_CONCEPT_PROMPT
from .utils.logger import get_logger
from .utils.output_manager import OutputManager
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
    detailed_dimension_reports: Dict[str, str]  # 各维度详细规划报告
    final_output: str              # 最终成果

    # 输出管理
    output_manager: OutputManager  # 输出管理器实例

    # Checkpoint相关
    checkpoint_enabled: bool       # 是否启用checkpoint
    last_checkpoint_id: str        # 最后保存的checkpoint ID
    checkpoint_manager: Any        # checkpoint管理器实例（不用类型注解避免循环导入）

    # 逐步执行模式
    step_mode: bool                # 是否启用逐步执行模式
    step_level: str                # 步骤级别（layer/dimension/skill）
    pause_after_step: bool         # 是否在当前步骤后暂停

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

            # 保存 Layer 1 结果（使用 OutputManager）
            output_manager: OutputManager = state.get("output_manager")
            if output_manager and output_manager.use_default_structure:
                try:
                    save_result = output_manager.save_layer1_results(
                        combined_report=result["analysis_report"],
                        dimension_reports=result.get("dimension_reports", {})
                    )
                    logger.info(f"[主图-Layer1] 保存了 {save_result['saved_count']} 个文件")
                except Exception as save_error:
                    logger.warning(f"[主图-Layer1] 保存结果时出错: {save_error}")

            # 保存checkpoint（如果启用）
            checkpoint_id = ""
            if state.get("checkpoint_enabled", False):
                checkpoint_manager = state.get("checkpoint_manager")
                if checkpoint_manager:
                    checkpoint_id = checkpoint_manager.save_checkpoint(
                        state={**state, **{
                            "analysis_report": result["analysis_report"],
                            "dimension_reports": result.get("dimension_reports", {}),
                            "layer_1_completed": True,
                            "current_layer": 2
                        }},
                        layer=1,
                        description="Layer 1 现状分析完成"
                    )

            return {
                "analysis_report": result["analysis_report"],
                "dimension_reports": result.get("dimension_reports", {}),  # 新增：传递维度报告
                "layer_1_completed": True,
                "current_layer": 2,
                "last_checkpoint_id": checkpoint_id,
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

            # 保存 Layer 2 结果（使用 OutputManager）
            output_manager: OutputManager = state.get("output_manager")
            if output_manager and output_manager.use_default_structure:
                try:
                    save_result = output_manager.save_layer2_results(
                        combined_report=result["concept_report"],
                        dimension_reports=result.get("concept_dimension_reports", {})
                    )
                    logger.info(f"[主图-Layer2] 保存了 {save_result['saved_count']} 个文件")
                except Exception as save_error:
                    logger.warning(f"[主图-Layer2] 保存结果时出错: {save_error}")

            # 保存checkpoint（如果启用）
            checkpoint_id = ""
            if state.get("checkpoint_enabled", False):
                checkpoint_manager = state.get("checkpoint_manager")
                if checkpoint_manager:
                    checkpoint_id = checkpoint_manager.save_checkpoint(
                        state={**state, **{
                            "planning_concept": result["concept_report"],
                            "concept_dimension_reports": result.get("concept_dimension_reports", {}),
                            "layer_2_completed": True,
                            "current_layer": 3
                        }},
                        layer=2,
                        description="Layer 2 规划思路完成"
                    )

            return {
                "planning_concept": result["concept_report"],
                "concept_dimension_reports": result.get("concept_dimension_reports", {}),  # 新增：传递规划维度报告
                "layer_2_completed": True,
                "current_layer": 3,
                "last_checkpoint_id": checkpoint_id,
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

            # 收集各维度详细规划报告
            detailed_dimension_reports = {
                "dimension_industry": result.get("industry_plan", ""),
                "dimension_master_plan": result.get("master_plan", ""),
                "dimension_traffic": result.get("traffic_plan", ""),
                "dimension_public_service": result.get("public_service_plan", ""),
                "dimension_infrastructure": result.get("infrastructure_plan", ""),
                "dimension_ecological": result.get("ecological_plan", ""),
                "dimension_disaster_prevention": result.get("disaster_prevention_plan", ""),
                "dimension_heritage": result.get("heritage_plan", ""),
                "dimension_landscape": result.get("landscape_plan", ""),
                "dimension_project_bank": result.get("project_bank", ""),
            }

            # 保存 Layer 3 结果（使用 OutputManager）
            output_manager: OutputManager = state.get("output_manager")
            if output_manager and output_manager.use_default_structure:
                try:
                    save_result = output_manager.save_layer3_results(
                        combined_report=result["detailed_plan_report"],
                        dimension_reports=detailed_dimension_reports
                    )
                    logger.info(f"[主图-Layer3] 保存了 {save_result['saved_count']} 个文件")
                except Exception as save_error:
                    logger.warning(f"[主图-Layer3] 保存结果时出错: {save_error}")

            # 保存checkpoint（如果启用）
            checkpoint_id = ""
            if state.get("checkpoint_enabled", False):
                checkpoint_manager = state.get("checkpoint_manager")
                if checkpoint_manager:
                    checkpoint_id = checkpoint_manager.save_checkpoint(
                        state={**state, **{
                            "detailed_plan": result["detailed_plan_report"],
                            "detailed_dimension_reports": detailed_dimension_reports,
                            "layer_3_completed": True,
                            "current_layer": 4
                        }},
                        layer=3,
                        description="Layer 3 详细规划完成"
                    )

            return {
                "detailed_plan": result["detailed_plan_report"],
                "detailed_dimension_reports": detailed_dimension_reports,
                "layer_3_completed": True,
                "current_layer": 4,
                "last_checkpoint_id": checkpoint_id,
                "messages": [AIMessage(content=f"详细规划已生成，包含 {len(result['completed_dimensions'])} 个专业维度。")]
            }
        else:
            logger.error(f"[主图-Layer3] 详细规划失败: {result.get('error', '未知错误')}")
            return {
                "detailed_plan": f"详细规划失败: {result.get('error', '未知错误')}",
                "detailed_dimension_reports": {},
                "layer_3_completed": False,
                "messages": [AIMessage(content="详细规划生成失败，请检查输入数据或稍后重试。")]
            }

    except Exception as e:
        logger.error(f"[主图-Layer3] 执行异常: {str(e)}")
        return {
            "detailed_plan": f"执行异常: {str(e)}",
            "detailed_dimension_reports": {},
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

    # 保存最终综合报告（使用 OutputManager）
    output_manager: OutputManager = state.get("output_manager")
    final_output_path = None
    if output_manager:
        try:
            final_output_path = output_manager.save_final_combined(final_output)
        except Exception as save_error:
            logger.warning(f"[主图-成果] 保存最终报告时出错: {save_error}")

    return {
        "final_output": final_output,
        "final_output_path": final_output_path,
        "messages": [AIMessage(content="最终规划成果已生成！")]
    }


# ==========================================
# 条件路由与审核
# ==========================================

def route_after_layer1(state: VillagePlanningState) -> Literal["pause", "human_review", "layer2", "end"]:
    """
    Layer 1 完成后的路由决策
    """
    if not state["layer_1_completed"]:
        # 分析失败，结束
        logger.warning("[主图-路由] 现状分析失败，流程终止")
        return "end"

    # 检查是否需要暂停（逐步执行模式）
    if state.get("step_mode", False) and state.get("pause_after_step", False):
        logger.info("[主图-路由] 进入暂停节点（逐步执行模式）")
        return "pause"

    if state.get("need_human_review", False):
        # 需要人工审核
        logger.info("[主图-路由] 进入人工审核环节")
        return "human_review"

    # 直接进入 Layer 2
    logger.info("[主图-路由] 直接进入规划思路阶段")
    return "layer2"


def route_after_layer2(state: VillagePlanningState) -> Literal["pause", "human_review", "layer3", "end"]:
    """
    Layer 2 完成后的路由决策
    """
    if not state["layer_2_completed"]:
        logger.warning("[主图-路由] 规划思路生成失败，流程终止")
        return "end"

    # 检查是否需要暂停（逐步执行模式）
    if state.get("step_mode", False) and state.get("pause_after_step", False):
        logger.info("[主图-路由] 进入暂停节点（逐步执行模式）")
        return "pause"

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
    人工审核节点（完整实现）

    使用ReviewUI显示审查界面并收集用户反馈。
    """
    logger.info(f"[主图-人工审核] 开始人工审核")

    # 获取当前需要审查的内容
    current_layer = state.get("current_layer", 1)
    if current_layer == 1:
        content = state.get("analysis_report", "")
        title = "现状分析报告"
    elif current_layer == 2:
        content = state.get("planning_concept", "")
        title = "规划思路报告"
    else:
        content = state.get("detailed_plan", "")
        title = "详细规划报告"

    # 获取可用checkpoint列表（用于回退）
    checkpoint_manager = state.get("checkpoint_manager")
    available_checkpoints = []
    if checkpoint_manager:
        available_checkpoints = checkpoint_manager.list_checkpoints()

    # 使用ReviewUI显示审查界面
    from .interactive.review_ui import ReviewUI
    ui = ReviewUI()
    result = ui.review_content(
        content=content,
        title=title,
        allow_rollback=True,
        available_checkpoints=available_checkpoints
    )

    # 处理审查结果
    action = result.get("action", "")

    if action == "approve":
        logger.info("[主图-人工审核] 审核通过")
        return {
            "messages": [AIMessage(content="人工审查通过")],
            "need_human_review": False,
            "human_feedback": ""
        }
    elif action == "reject":
        logger.info(f"[主图-人工审核] 审核驳回，反馈: {result.get('feedback', '')}")
        return {
            "messages": [AIMessage(content=f"人工审查驳回，反馈: {result.get('feedback', '')}")],
            "need_human_review": False,
            "human_feedback": result.get("feedback", ""),
            "need_revision": True  # 标记需要修复
        }
    elif action == "rollback":
        logger.info(f"[主图-人工审核] 触发回退到: {result.get('checkpoint_id', '')}")
        return {
            "messages": [AIMessage(content=f"回退到checkpoint: {result.get('checkpoint_id', '')}")],
            "trigger_rollback": True,
            "rollback_target": result.get("checkpoint_id", "")
        }
    elif action == "quit":
        logger.info("[主图-人工审核] 用户退出")
        return {
            "messages": [AIMessage(content="用户退出程序")],
            "quit_requested": True
        }
    else:
        # 默认通过
        return {
            "messages": [AIMessage(content="人工审查完成（默认通过）")],
            "need_human_review": False
        }


def pause_node(state: VillagePlanningState) -> Dict[str, Any]:
    """
    暂停节点，等待用户继续

    用于逐步执行模式。
    """
    logger.info(f"[主图-暂停] 进入暂停节点")

    if state.get("step_mode", False):
        from .interactive.cli import InteractiveCLI
        cli = InteractiveCLI()

        # 显示进度
        cli.show_progress(state)

        # 等待用户命令
        while True:
            command = cli.show_menu()
            result = cli.execute_command(command, state)

            action = result.get("action", "")

            if action == "continue":
                logger.info("[主图-暂停] 继续执行")
                return {
                    "pause_after_step": False,
                    "messages": [AIMessage(content="继续执行")]
                }
            elif action == "rollback":
                checkpoint_id = result.get("checkpoint_id", "")
                logger.info(f"[主图-暂停] 回退到: {checkpoint_id}")
                return {
                    "trigger_rollback": True,
                    "rollback_target": checkpoint_id
                }
            elif action == "quit":
                logger.info("[主图-暂停] 用户退出")
                return {
                    "quit_requested": True,
                    "messages": [AIMessage(content="用户退出程序")]
                }
            # 其他action保持暂停状态

    # 如果不是step模式，直接继续
    return {}


def revision_node(state: VillagePlanningState) -> Dict[str, Any]:
    """
    修复节点：基于人工反馈修复特定维度

    当人工审查驳回时触发。
    """
    logger.info(f"[主图-修复] 进入修复节点")

    feedback = state.get("human_feedback", "")
    if not feedback:
        logger.warning("[主图-修复] 没有反馈信息，跳过修复")
        return {"need_revision": False}

    try:
        from .revision.revision_manager import RevisionManager

        manager = RevisionManager()

        # 1. 识别需要修复的维度
        dimensions = manager.parse_feedback(feedback)

        # 2. 用户确认（混合模式）
        dimensions = manager.confirm_dimensions(dimensions)

        if not dimensions:
            logger.info("[主图-修复] 用户取消修复")
            return {"need_revision": False}

        # 3. 逐个修复维度
        revised_results = {}
        detailed_dimension_reports = state.get("detailed_dimension_reports", {})

        # 维度键名映射
        dimension_key_map = {
            "industry": "dimension_industry",
            "master_plan": "dimension_master_plan",
            "traffic": "dimension_traffic",
            "public_service": "dimension_public_service",
            "infrastructure": "dimension_infrastructure",
            "ecological": "dimension_ecological",
            "disaster_prevention": "dimension_disaster_prevention",
            "heritage": "dimension_heritage",
            "landscape": "dimension_landscape",
            "project_bank": "dimension_project_bank"
        }

        for dimension in dimensions:
            # 获取原始结果
            key = dimension_key_map.get(dimension)
            if key and key in detailed_dimension_reports:
                original_result = detailed_dimension_reports[key]

                # 使用skill进行修复
                from .core.dimension_skill import SkillFactory
                skill = SkillFactory.create_skill(dimension)

                revised_result = skill.execute_with_feedback(
                    state=state,
                    feedback=feedback,
                    original_result=original_result,
                    revision_count=0
                )

                revised_results[key] = revised_result
                logger.info(f"[主图-修复] 维度 {dimension} 修复完成")

        # 4. 更新状态
        if revised_results:
            # 更新detailed_dimension_reports
            updated_reports = {**detailed_dimension_reports, **revised_results}

            # 重新组合综合报告
            # （简化处理：实际可能需要更复杂的组合逻辑）
            updated_detailed_plan = state.get("detailed_plan", "")
            for key, result in revised_results.items():
                dimension_name = key.replace("dimension_", "")
                updated_detailed_plan += f"\n\n## 修复后的{dimension_name}规划\n\n{result}"

            return {
                "detailed_dimension_reports": updated_reports,
                "detailed_plan": updated_detailed_plan,
                "need_revision": False,
                "messages": [AIMessage(content=f"已修复 {len(revised_results)} 个维度")]
            }
        else:
            return {"need_revision": False}

    except Exception as e:
        logger.error(f"[主图-修复] 修复失败: {str(e)}")
        return {
            "need_revision": False,
            "messages": [AIMessage(content=f"修复失败: {str(e)}")]
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
    builder.add_node("pause", pause_node)
    builder.add_node("revision", revision_node)

    # 构建执行流程
    builder.add_edge(START, "layer1_analysis")

    # Layer 1 -> pause/审核/layer2/end
    builder.add_conditional_edges(
        "layer1_analysis",
        route_after_layer1,
        {
            "pause": "pause",
            "human_review": "human_review",
            "layer2": "layer2_concept",
            "end": END
        }
    )

    # pause -> layer2
    builder.add_edge("pause", "layer2_concept")

    # 人工审核 -> 检查是否需要修复
    builder.add_conditional_edges(
        "human_review",
        route_after_human_review,
        {
            "revision": "revision",
            "layer2": "layer2_concept",
            "end": END
        }
    )

    # revision -> layer2 (修复后继续)
    builder.add_edge("revision", "layer2_concept")

    # Layer 2 -> pause/审核/layer3/end
    builder.add_conditional_edges(
        "layer2_concept",
        route_after_layer2,
        {
            "pause": "pause",
            "human_review": "human_review",
            "layer3": "layer3_detail",
            "end": END
        }
    )

    # pause -> layer3
    builder.add_conditional_edges(
        "pause",
        route_after_pause,
        {
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


def route_after_human_review(state: VillagePlanningState) -> Literal["revision", "layer2", "end"]:
    """
    人工审核后的路由决策

    根据审核结果决定是否需要修复
    """
    if state.get("need_revision", False):
        logger.info("[主图-路由] 进入修复环节")
        return "revision"

    # 默认继续执行
    current_layer = state.get("current_layer", 1)
    if current_layer == 1:
        return "layer2"
    elif current_layer == 2:
        return "layer3"
    else:
        return "end"


def route_after_pause(state: VillagePlanningState) -> Literal["layer3", "end"]:
    """
    暂停节点后的路由决策

    根据当前层级决定下一步
    """
    current_layer = state.get("current_layer", 1)

    if current_layer == 2:
        # 从layer 1暂停后继续，进入layer 2
        return "layer3" if state.get("layer_2_completed", False) else "layer3"
    elif current_layer == 3:
        # 从layer 2暂停后继续，进入layer 3
        return "layer3"
    else:
        return "end"


# ==========================================
# 对外接口
# ==========================================

def run_village_planning(
    project_name: str,
    village_data: str,
    task_description: str = "制定村庄总体规划方案",
    constraints: str = "无特殊约束",
    need_human_review: bool = False,
    stream_mode: bool = False,
    output_manager: OutputManager = None,
    custom_output_path: str = None,
    step_mode: bool = False,
    step_level: str = "layer"
) -> Dict[str, Any]:
    """
    执行村庄规划主流程

    新增功能：
    - village_data可以是文件路径，会自动加载
    - 支持多种格式（txt, pdf, docx等）
    - 自动保存结果到默认目录或自定义路径

    Args:
        project_name: 项目/村庄名称
        village_data: 村庄基础数据（文件路径或直接文本）
        task_description: 规划任务描述
        constraints: 约束条件
        need_human_review: 是否需要人工审核
        stream_mode: 是否使用流式输出
        output_manager: 输出管理器实例（可选，如果不提供则自动创建）
        custom_output_path: 自定义输出路径（可选，如果提供则覆盖默认行为）

    Returns:
        包含最终成果的字典
    """
    logger.info(f"[主图-调用] 开始执行村庄规划: {project_name}")

    # 智能检测village_data是文件路径还是直接数据
    from .tools.file_manager import VillageDataManager
    manager = VillageDataManager()

    # 如果看起来像文件路径，尝试加载
    if len(village_data) < 200 and ("\n" not in village_data or Path(village_data).exists()):
        try:
            result = manager.load_data(village_data)
            if result["success"]:
                village_data = result["content"]
                logger.info(f"[主图-调用] 从文件加载数据: {result['metadata'].get('filename', 'unknown')}, {len(village_data)} 字符")
        except:
            # 当作直接数据使用
            pass

    # 创建或使用提供的 OutputManager
    if output_manager is None:
        from .utils.output_manager import create_output_manager
        output_manager = create_output_manager(
            project_name=project_name,
            custom_output_path=custom_output_path
        )

    # 确保输出目录存在
    if output_manager:
        output_manager.ensure_directories()

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
        "detailed_dimension_reports": {},  # 新增：初始化详细规划维度字典
        "final_output": "",
        "output_manager": output_manager,  # 新增：输出管理器
        "checkpoint_enabled": True,  # 默认启用checkpoint
        "last_checkpoint_id": "",
        "checkpoint_manager": None,  # 稍后初始化
        "step_mode": step_mode,  # 使用传入的step_mode参数
        "step_level": step_level,  # 使用传入的step_level参数
        "pause_after_step": step_mode,  # 如果启用step_mode，在每步后暂停
        "messages": []
    }

    # 初始化checkpoint管理器（如果启用）
    if initial_state["checkpoint_enabled"]:
        from .checkpoint.checkpoint_manager import CheckpointManager
        checkpoint_manager = CheckpointManager(
            project_name=project_name,
            timestamp=output_manager.timestamp if output_manager else None
        )
        initial_state["checkpoint_manager"] = checkpoint_manager
        logger.info("[主图-调用] Checkpoint管理器已初始化")

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
            "final_output_path": final_state.get("final_output_path"),
            "analysis_report": final_state.get("analysis_report", ""),
            "planning_concept": final_state.get("planning_concept", ""),
            "detailed_plan": final_state.get("detailed_plan", ""),
            "all_layers_completed": all([
                final_state.get("layer_1_completed", False),
                final_state.get("layer_2_completed", False),
                final_state.get("layer_3_completed", False)
            ]),
            "output_manager": output_manager
        }

    except Exception as e:
        logger.error(f"[主图-调用] 执行失败: {str(e)}")
        return {
            "success": False,
            "error": str(e),
            "final_output": f"执行失败: {str(e)}"
        }


def resume_from_checkpoint(
    checkpoint_id: str,
    project_name: str,
    output_manager: OutputManager = None
) -> Dict[str, Any]:
    """
    从checkpoint恢复执行

    Args:
        checkpoint_id: checkpoint ID
        project_name: 项目名称
        output_manager: 输出管理器（可选）

    Returns:
        执行结果字典
    """
    logger.info(f"[主图-恢复] 从checkpoint恢复: {checkpoint_id}")

    try:
        # 创建checkpoint管理器
        from .checkpoint.checkpoint_manager import CheckpointManager
        checkpoint_manager = CheckpointManager(project_name)

        # 加载checkpoint
        state = checkpoint_manager.load_checkpoint(checkpoint_id)
        if not state:
            return {
                "success": False,
                "error": f"无法加载checkpoint: {checkpoint_id}"
            }

        # 重建output_manager
        if output_manager is None and state.get("output_manager"):
            try:
                from .utils.output_manager import create_output_manager
                output_manager = create_output_manager(
                    project_name=project_name
                )
            except Exception as e:
                logger.warning(f"[主图-恢复] 重建output_manager失败: {e}")

        # 获取当前层级
        current_layer = state.get("current_layer", 1)

        # 根据当前层级决定执行路径
        if current_layer == 2:
            # Layer 1完成，继续执行Layer 2
            logger.info("[主图-恢复] Layer 1已完成，从Layer 2继续")

            # 确保输出目录存在
            if output_manager:
                output_manager.ensure_directories()

            # 创建主图
            graph = create_village_planning_graph()

            # 更新状态
            state["output_manager"] = output_manager
            state["checkpoint_enabled"] = True
            state["checkpoint_manager"] = checkpoint_manager

            # 从Layer 2开始执行
            final_state = graph.invoke(state)

            return {
                "success": True,
                "final_output": final_state.get("final_output", ""),
                "resumed_from": checkpoint_id,
                "all_layers_completed": all([
                    final_state.get("layer_1_completed", False),
                    final_state.get("layer_2_completed", False),
                    final_state.get("layer_3_completed", False)
                ]),
                "output_manager": output_manager
            }

        elif current_layer == 3:
            # Layer 2完成，继续执行Layer 3
            logger.info("[主图-恢复] Layer 2已完成，从Layer 3继续")

            # 确保输出目录存在
            if output_manager:
                output_manager.ensure_directories()

            # 创建主图
            graph = create_village_planning_graph()

            # 更新状态
            state["output_manager"] = output_manager
            state["checkpoint_enabled"] = True
            state["checkpoint_manager"] = checkpoint_manager

            # 从Layer 3开始执行
            final_state = graph.invoke(state)

            return {
                "success": True,
                "final_output": final_state.get("final_output", ""),
                "resumed_from": checkpoint_id,
                "all_layers_completed": all([
                    final_state.get("layer_1_completed", False),
                    final_state.get("layer_2_completed", False),
                    final_state.get("layer_3_completed", False)
                ]),
                "output_manager": output_manager
            }

        elif current_layer >= 4:
            # 所有层级都已完成
            logger.info("[主图-恢复] 所有层级已完成，无需继续执行")
            return {
                "success": True,
                "final_output": state.get("final_output", ""),
                "resumed_from": checkpoint_id,
                "all_layers_completed": True,
                "message": "所有层级已完成"
            }

        else:
            return {
                "success": False,
                "error": f"无效的当前层级: {current_layer}"
            }

    except Exception as e:
        logger.error(f"[主图-恢复] 恢复失败: {str(e)}")
        return {
            "success": False,
            "error": str(e)
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
