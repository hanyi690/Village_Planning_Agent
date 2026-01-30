"""
村庄规划主图 (Main Graph) - 编排层

管理三层规划流程的执行：
1. Layer 1: 现状分析（使用现状分析子图）
2. Layer 2: 规划思路生成
3. Layer 3: 详细规划

关键变更：
- 使用新的节点类（Layer节点和工具节点）
- tool_bridge_node统一处理工具调用
- 移除UI代码到工具层
"""

from typing import TypedDict, List, Dict, Any, Literal
from typing_extensions import Annotated
from pathlib import Path
from langgraph.graph import StateGraph, END, START
from langgraph.graph.message import add_messages
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage
import operator

from ..core.config import LLM_MODEL, MAX_TOKENS
from ..core.prompts import SYSTEM_PROMPT, PLANNING_CONCEPT_PROMPT
from ..utils.logger import get_logger
from ..utils.output_manager import OutputManager
from ..subgraphs.analysis_subgraph import call_analysis_subgraph
from ..subgraphs.concept_subgraph import call_concept_subgraph
from ..subgraphs.detailed_plan_subgraph import call_detailed_plan_subgraph

# 使用新工具
from ..tools.checkpoint_tool import CheckpointTool
from ..tools.interactive_tool import InteractiveTool
from ..tools.revision_tool import RevisionTool

# 使用新的节点类
from ..nodes import (
    Layer1AnalysisNode,
    Layer2ConceptNode,
    Layer3DetailNode,
    ToolBridgeNode,
    PauseManagerNode
)
from ..nodes.tool_nodes import _run_human_review, _run_pause_interaction, _run_revision

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
    need_revision: bool            # 是否需要修复

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
    checkpoint_manager: Any        # checkpoint工具实例

    # 逐步执行模式
    step_mode: bool                # 是否启用逐步执行模式
    step_level: str                # 步骤级别（layer/dimension/skill）
    pause_after_step: bool         # 是否在当前步骤后暂停

    # 路由控制标志
    quit_requested: bool           # 用户请求退出
    trigger_rollback: bool         # 触发回退
    rollback_target: str           # 回退目标checkpoint ID

    # 消息历史
    messages: Annotated[List[BaseMessage], add_messages]


# ==========================================
# LLM 辅助函数
# ==========================================

def _get_llm():
    """获取 LLM 实例，使用统一的 LLM 工厂"""
    from ..core.llm_factory import create_llm
    return create_llm(model=LLM_MODEL, temperature=0.7, max_tokens=MAX_TOKENS)


# ==========================================
# Layer执行节点
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
                    # 使用新工具
                    if isinstance(checkpoint_manager, CheckpointTool):
                        save_result = checkpoint_manager.save(
                            state={**state, **{
                                "analysis_report": result["analysis_report"],
                                "dimension_reports": result.get("dimension_reports", {}),
                                "layer_1_completed": True,
                                "current_layer": 2
                            }},
                            layer=1,
                            description="Layer 1 现状分析完成"
                        )
                        checkpoint_id = save_result["checkpoint_id"] if save_result["success"] else ""
                    else:
                        # 兼容旧版本
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
                "dimension_reports": result.get("dimension_reports", {}),
                "layer_1_completed": True,
                "current_layer": 2,
                "last_checkpoint_id": checkpoint_id,
                "messages": [AIMessage(content=f"现状分析完成，生成了 {len(result['analysis_report'])} 字符的综合报告。")]
            }
        else:
            logger.error(f"[主图-Layer1] 现状分析失败: {result['analysis_report']}")
            return {
                "analysis_report": f"现状分析失败: {result['analysis_report']}",
                "dimension_reports": {},
                "layer_1_completed": False,
                "messages": [AIMessage(content="现状分析失败，请检查输入数据或稍后重试。")]
            }

    except Exception as e:
        logger.error(f"[主图-Layer1] 执行异常: {str(e)}")
        return {
            "analysis_report": f"执行异常: {str(e)}",
            "dimension_reports": {},
            "layer_1_completed": False,
            "messages": [AIMessage(content=f"现状分析过程中发生错误: {str(e)}")]
        }


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
            dimension_reports=state.get("dimension_reports", {}),
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
                    # 使用新工具
                    if isinstance(checkpoint_manager, CheckpointTool):
                        save_result = checkpoint_manager.save(
                            state={**state, **{
                                "planning_concept": result["concept_report"],
                                "concept_dimension_reports": result.get("concept_dimension_reports", {}),
                                "layer_2_completed": True,
                                "current_layer": 3
                            }},
                            layer=2,
                            description="Layer 2 规划思路完成"
                        )
                        checkpoint_id = save_result["checkpoint_id"] if save_result["success"] else ""
                    else:
                        # 兼容旧版本
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
                "concept_dimension_reports": result.get("concept_dimension_reports", {}),
                "layer_2_completed": True,
                "current_layer": 3,
                "last_checkpoint_id": checkpoint_id,
                "messages": [AIMessage(content=f"规划思路已生成，长度 {len(result['concept_report'])} 字符。")]
            }
        else:
            logger.error(f"[主图-Layer2] 规划思路失败: {result['concept_report']}")
            return {
                "planning_concept": f"规划思路失败: {result['concept_report']}",
                "concept_dimension_reports": {},
                "layer_2_completed": False,
                "messages": [AIMessage(content="规划思路生成失败，请检查输入数据或稍后重试。")]
            }

    except Exception as e:
        logger.error(f"[主图-Layer2] 执行异常: {str(e)}")
        return {
            "planning_concept": f"执行异常: {str(e)}",
            "concept_dimension_reports": {},
            "layer_2_completed": False,
            "messages": [AIMessage(content=f"规划思路生成过程中发生错误: {str(e)}")]
        }


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
            dimension_reports=state.get("dimension_reports", {}),
            concept_dimension_reports=state.get("concept_dimension_reports", {}),
            task_description=state.get("task_description", "制定村庄详细规划"),
            constraints=state.get("constraints", "无特殊约束"),
            required_dimensions=state.get("required_dimensions"),
            enable_human_review=state.get("need_human_review", False)
        )

        if result["success"]:
            logger.info(f"[主图-Layer3] 详细规划完成，报告长度: {len(result['detailed_plan_report'])} 字符")
            logger.info(f"[主图-Layer3] 已完成维度: {result['completed_dimensions']}")

            # 收集各维度详细规划报告
            # 键名不带前缀，与 OutputManager 期望的格式一致
            detailed_dimension_reports = {
                "industry": result.get("industry_plan", ""),
                "master_plan": result.get("master_plan", ""),
                "traffic": result.get("traffic_plan", ""),
                "public_service": result.get("public_service_plan", ""),
                "infrastructure": result.get("infrastructure_plan", ""),
                "ecological": result.get("ecological_plan", ""),
                "disaster_prevention": result.get("disaster_prevention_plan", ""),
                "heritage": result.get("heritage_plan", ""),
                "landscape": result.get("landscape_plan", ""),
                "project_bank": result.get("project_bank", ""),
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
                    # 使用新工具
                    if isinstance(checkpoint_manager, CheckpointTool):
                        save_result = checkpoint_manager.save(
                            state={**state, **{
                                "detailed_plan": result["detailed_plan_report"],
                                "detailed_dimension_reports": detailed_dimension_reports,
                                "layer_3_completed": True,
                                "current_layer": 4
                            }},
                            layer=3,
                            description="Layer 3 详细规划完成"
                        )
                        checkpoint_id = save_result["checkpoint_id"] if save_result["success"] else ""
                    else:
                        # 兼容旧版本
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
# 工具桥接节点（统一工具调用）
# ==========================================

def tool_bridge_node(state: VillagePlanningState) -> Dict[str, Any]:
    """
    工具桥接节点 - 统一工具调用入口

    根据状态标志调用相应的工具：
    - need_human_review: 人工审查（使用InteractiveTool）
    - pause_after_step: 暂停交互（使用InteractiveTool）
    - need_revision: 修复（使用RevisionTool）

    Returns:
        更新后的状态字典
    """
    logger.info(f"[主图-工具桥接] 进入工具桥接节点")

    # 优先级：人工审查 > 暂停 > 修复
    if state.get("need_human_review", False):
        return _run_human_review(state)
    elif state.get("pause_after_step", False):
        return _run_pause_interaction(state)
    elif state.get("need_revision", False):
        return _run_revision(state)
    else:
        return state


def _run_human_review(state: VillagePlanningState) -> Dict[str, Any]:
    """执行人工审查（使用InteractiveTool）"""
    logger.info(f"[主图-人工审查] 开始人工审查")

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
        # 使用新工具
        if isinstance(checkpoint_manager, CheckpointTool):
            list_result = checkpoint_manager.list()
            if list_result["success"]:
                available_checkpoints = list_result["checkpoints"]
        else:
            # 兼容旧版本
            available_checkpoints = checkpoint_manager.list_checkpoints()

    # 使用InteractiveTool显示审查界面
    tool = InteractiveTool()
    result = tool.review_content(
        content=content,
        title=title,
        allow_rollback=True,
        available_checkpoints=available_checkpoints
    )

    # 处理审查结果
    action = result.get("action", "")

    if action == "approve":
        logger.info("[主图-人工审查] 审核通过")
        return {
            "messages": [AIMessage(content="人工审查通过")],
            "need_human_review": False,
            "human_feedback": ""
        }
    elif action == "reject":
        logger.info(f"[主图-人工审查] 审核驳回，反馈: {result.get('feedback', '')}")
        return {
            "messages": [AIMessage(content=f"人工审查驳回，反馈: {result.get('feedback', '')}")],
            "need_human_review": False,
            "human_feedback": result.get("feedback", ""),
            "need_revision": True
        }
    elif action == "rollback":
        logger.info(f"[主图-人工审查] 触发回退到: {result.get('checkpoint_id', '')}")
        return {
            "messages": [AIMessage(content=f"回退到checkpoint: {result.get('checkpoint_id', '')}")],
            "trigger_rollback": True,
            "rollback_target": result.get("checkpoint_id", "")
        }
    elif action == "quit":
        logger.info("[主图-人工审查] 用户退出")
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


def _run_pause_interaction(state: VillagePlanningState) -> Dict[str, Any]:
    """执行暂停交互（使用InteractiveTool）"""
    logger.info(f"[主图-暂停] 进入暂停节点")

    tool = InteractiveTool()

    # 显示进度
    tool.show_progress(state)

    # 交互循环
    while True:
        # 获取用户命令
        menu_result = tool.show_menu()
        if not menu_result["success"]:
            continue

        command = menu_result["command"]
        exec_result = tool.execute_command(command, state)

        action = exec_result.get("action", "")
        modified_state = exec_result.get("modified_state", {})

        # Preserve layer completion state
        preserved_state = {
            "layer_1_completed": state.get("layer_1_completed", False),
            "layer_2_completed": state.get("layer_2_completed", False),
            "layer_3_completed": state.get("layer_3_completed", False),
            "current_layer": state.get("current_layer", 1),
        }

        if action == "continue":
            logger.info("[主图-暂停] 继续执行")
            return {
                "pause_after_step": False,
                "messages": [AIMessage(content="继续执行")],
                **preserved_state,
                **modified_state
            }
        elif action == "rollback":
            checkpoint_id = exec_result.get("checkpoint_id", "")
            logger.info(f"[主图-暂停] 回退到: {checkpoint_id}")
            return {
                "trigger_rollback": True,
                "rollback_target": checkpoint_id,
                "messages": [AIMessage(content=f"回退到checkpoint: {checkpoint_id}")],
                **preserved_state,
                **modified_state
            }
        elif action == "quit":
            logger.info("[主图-暂停] 用户退出")
            return {
                "quit_requested": True,
                "messages": [AIMessage(content="用户退出程序")],
                **preserved_state,
                **modified_state
            }
        # 其他action保持暂停状态


def _run_revision(state: VillagePlanningState) -> Dict[str, Any]:
    """执行修复（使用RevisionTool）"""
    logger.info(f"[主图-修复] 进入修复节点")

    feedback = state.get("human_feedback", "")
    if not feedback:
        logger.warning("[主图-修复] 没有反馈信息，跳过修复")
        return {"need_revision": False}

    try:
        tool = RevisionTool()

        # 1. 识别需要修复的维度
        parse_result = tool.parse_feedback(feedback)
        dimensions = parse_result["dimensions"] if parse_result["success"] else []

        # 2. 用户确认（使用InteractiveTool）
        # 注意：UI确认在interactive_tool中完成，这里简化处理
        if not dimensions:
            logger.info("[主图-修复] 未识别到需要修复的维度")
            return {"need_revision": False}

        # 3. 逐个修复维度
        revise_result = tool.revise_multiple(
            dimensions=dimensions,
            state=state,
            feedback=feedback
        )

        if not revise_result["success"]:
            logger.error(f"[主图-修复] 批量修复失败: {revise_result['error']}")
            return {"need_revision": False}

        revised_results = revise_result["revised_results"]
        detailed_dimension_reports = state.get("detailed_dimension_reports", {})

        # 维度键名映射 - 从子图的键名映射到状态中的键名
        # 子图返回: "industry", "master_plan", 等（不带前缀）
        # 状态中保存: 同样的键名（不带前缀）
        # 维度名称到友好名称的映射（用于显示）
        dimension_names = {
            "industry": "产业规划",
            "master_plan": "村域总体规划",
            "traffic": "综合交通规划",
            "public_service": "公共服务设施规划",
            "infrastructure": "基础设施规划",
            "ecological": "生态绿地系统规划",
            "disaster_prevention": "防灾减灾规划",
            "heritage": "历史文化保护规划",
            "landscape": "村庄风貌规划",
            "project_bank": "项目库"
        }

        # 重新组合综合报告
        updated_detailed_plan = state.get("detailed_plan", "")
        for dimension, revised_result in revised_results.items():
            dimension_name = dimension_names.get(dimension, dimension)
            updated_detailed_plan += f"\n\n## 修复后的{dimension_name}\n\n{revised_result}"
            # 同时更新状态中的维度报告
            detailed_dimension_reports[dimension] = revised_result

        return {
            "detailed_dimension_reports": detailed_dimension_reports,
            "detailed_plan": updated_detailed_plan,
            "need_revision": False,
            "messages": [AIMessage(content=f"已修复 {len(revised_results)} 个维度")]
        }

    except Exception as e:
        logger.error(f"[主图-修复] 修复失败: {str(e)}")
        return {
            "need_revision": False,
            "messages": [AIMessage(content=f"修复失败: {str(e)}")]
        }


def pause_manager_node(state: VillagePlanningState) -> Dict[str, Any]:
    """
    暂停管理节点：统一管理各种暂停场景

    支持的暂停场景：
    - step_mode: 逐步执行模式
    - 人工审核: need_human_review (未来扩展)
    - 其他暂停场景: 易于扩展

    在step模式下，为下一层执行准备暂停状态，确保每一层完成后都能正确暂停。
    """
    # Step模式：设置暂停
    if state.get("step_mode", False):
        logger.info("[暂停管理] Step模式已启用，设置pause_after_step=True")
        return {"pause_after_step": True}

    # 未来扩展：其他暂停场景
    # if state.get("need_human_review", False):
    #     logger.info("[暂停管理] 人工审核模式，设置pause_after_step=True")
    #     return {"pause_after_step": True}

    return {}


# ==========================================
# 路由决策
# ==========================================

def route_after_pause(state: VillagePlanningState) -> Literal["layer1_analysis", "layer2_concept", "layer3_detail"]:
    """
    pause节点后的路由：根据current_layer决定执行哪个layer

    这个路由函数确保pause节点能够正确地将流程引导到当前应该执行的layer。
    """
    current_layer = state.get("current_layer", 1)
    logger.info(f"[主图-路由] 从pause节点路由到Layer {current_layer}")

    if current_layer == 1:
        return "layer1_analysis"
    elif current_layer == 2:
        return "layer2_concept"
    elif current_layer == 3:
        return "layer3_detail"
    else:
        # 默认返回layer1
        logger.warning(f"[主图-路由] 无效的current_layer: {current_layer}，默认路由到Layer 1")
        return "layer1_analysis"


def route_after_layer1(state: VillagePlanningState) -> Literal["tool_bridge", "layer2", "end"]:
    """Layer 1 完成后的路由决策"""
    if not state["layer_1_completed"]:
        logger.warning("[主图-路由] 现状分析失败，流程终止")
        return "end"

    # 检查是否需要暂停或人工审核
    if state.get("step_mode", False) and state.get("pause_after_step", False):
        logger.info("[主图-路由] 进入工具桥接（暂停）")
        return "tool_bridge"

    if state.get("need_human_review", False):
        logger.info("[主图-路由] 进入工具桥接（人工审核）")
        return "tool_bridge"

    logger.info("[主图-路由] 直接进入规划思路阶段")
    return "layer2"


def route_after_layer2(state: VillagePlanningState) -> Literal["tool_bridge", "layer3", "end"]:
    """Layer 2 完成后的路由决策"""
    if not state["layer_2_completed"]:
        logger.warning("[主图-路由] 规划思路生成失败，流程终止")
        return "end"

    # 检查是否需要暂停或人工审核
    if state.get("step_mode", False) and state.get("pause_after_step", False):
        logger.info("[主图-路由] 进入工具桥接（暂停）")
        return "tool_bridge"

    if state.get("need_human_review", False):
        logger.info("[主图-路由] 进入工具桥接（人工审核）")
        return "tool_bridge"

    logger.info("[主图-路由] 进入详细规划阶段")
    return "layer3"


def route_after_layer3(state: VillagePlanningState) -> Literal["final", "end"]:
    """Layer 3 完成后的路由决策"""
    if state["layer_3_completed"]:
        logger.info("[主图-路由] 进入最终成果生成")
        return "final"
    else:
        logger.warning("[主图-路由] 详细规划失败，流程终止")
        return "end"


def route_after_tool_bridge(state: VillagePlanningState) -> Literal["pause", "layer2_concept", "layer3_detail", "end"]:
    """
    工具桥接后的路由决策

    决定从tool_bridge出来后：
    - 如果step_mode开启：路由到pause节点（设置暂停状态）
    - 否则：直接路由到对应的layer执行节点
    """
    current_layer = state.get("current_layer", 1)

    # 检查退出标志
    if state.get("quit_requested", False):
        logger.info("[主图-路由] 用户请求退出，流程结束")
        return "end"

    # 检查回退标志
    if state.get("trigger_rollback", False):
        logger.info("[主图-路由] 触发回退，流程结束（由checkpoint_tool处理）")
        return "end"

    # 检查修复标志
    if state.get("need_revision", False):
        # 修复后继续
        if current_layer == 1:
            if state.get("step_mode", False):
                logger.info("[主图-路由] Step模式：tool_bridge → pause → layer2")
                return "pause"
            return "layer2_concept"
        elif current_layer == 2:
            if state.get("step_mode", False):
                logger.info("[主图-路由] Step模式：tool_bridge → pause → layer3")
                return "pause"
            return "layer3_detail"
        else:
            return "end"

    # 根据current_layer和step_mode决定下一步
    if current_layer == 1:
        # Layer 1: 从tool_bridge回到layer 1（通常是回退后）或进入layer 2
        if state.get("step_mode", False):
            logger.info("[主图-路由] Step模式：tool_bridge → pause → layer2")
            return "pause"
        logger.info("[主图-路由] 直接进入Layer 2")
        return "layer2_concept"
    elif current_layer == 2:
        # Layer 2: 从tool_bridge继续到layer 2
        if state.get("step_mode", False):
            logger.info("[主图-路由] Step模式：tool_bridge → pause → layer2")
            return "pause"
        logger.info("[主图-路由] 直接进入Layer 2")
        return "layer2_concept"
    elif current_layer == 3:
        # Layer 3: 从tool_bridge继续到layer 3
        if state.get("step_mode", False):
            logger.info("[主图-路由] Step模式：tool_bridge → pause → layer3")
            return "pause"
        logger.info("[主图-路由] 直接进入Layer 3")
        return "layer3_detail"
    else:
        logger.info("[主图-路由] 流程结束")
        return "end"


# ==========================================
# 构建主图
# ==========================================

def create_village_planning_graph() -> StateGraph:
    """
    创建村庄规划主图

    使用新的节点类实例替代旧的函数节点。

    Returns:
        编译后的 StateGraph 实例
    """
    logger.info("[主图构建] 开始构建村庄规划主图")

    # 创建节点实例
    pause_node = PauseManagerNode()
    layer1_node = Layer1AnalysisNode()
    layer2_node = Layer2ConceptNode()
    layer3_node = Layer3DetailNode()
    tool_bridge_node = ToolBridgeNode()

    builder = StateGraph(VillagePlanningState)

    # 添加节点（使用节点实例的__call__方法）
    builder.add_node("pause", pause_node)
    builder.add_node("layer1_analysis", layer1_node)
    builder.add_node("layer2_concept", layer2_node)
    builder.add_node("layer3_detail", layer3_node)
    builder.add_node("generate_final", generate_final_output)
    builder.add_node("tool_bridge", tool_bridge_node)

    # 构建执行流程
    # START -> pause (暂停管理节点设置初始暂停状态)
    builder.add_edge(START, "pause")

    # pause -> 根据current_layer路由到对应的layer
    builder.add_conditional_edges(
        "pause",
        route_after_pause,
        {
            "layer1_analysis": "layer1_analysis",
            "layer2_concept": "layer2_concept",
            "layer3_detail": "layer3_detail"
        }
    )

    # Layer 1 -> tool_bridge/layer2/end
    builder.add_conditional_edges(
        "layer1_analysis",
        route_after_layer1,
        {
            "tool_bridge": "tool_bridge",
            "layer2": "layer2_concept",
            "end": END
        }
    )

    # tool_bridge -> pause/layer2/layer3/end
    # 在step模式下，tool_bridge会路由到pause节点以重置暂停状态
    builder.add_conditional_edges(
        "tool_bridge",
        route_after_tool_bridge,
        {
            "pause": "pause",
            "layer2_concept": "layer2_concept",
            "layer3_detail": "layer3_detail",
            "end": END
        }
    )

    # Layer 2 -> tool_bridge/layer3/end
    builder.add_conditional_edges(
        "layer2_concept",
        route_after_layer2,
        {
            "tool_bridge": "tool_bridge",
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
    stream_mode: bool = False,
    output_manager: OutputManager = None,
    custom_output_path: str = None,
    step_mode: bool = False,
    step_level: str = "layer"
) -> Dict[str, Any]:
    """
    执行村庄规划主流程

    Args:
        project_name: 项目/村庄名称
        village_data: 村庄基础数据（文件路径或直接文本）
        task_description: 规划任务描述
        constraints: 约束条件
        need_human_review: 是否需要人工审核
        stream_mode: 是否使用流式输出
        output_manager: 输出管理器实例（可选）
        custom_output_path: 自定义输出路径（可选）
        step_mode: 是否启用逐步执行模式
        step_level: 步骤级别

    Returns:
        包含最终成果的字典
    """
    from ..core.langsmith_integration import get_langsmith_manager

    # 检查LangSmith状态
    langsmith = get_langsmith_manager()
    if langsmith.is_enabled():
        logger.info(f"[主图-调用] LangSmith tracing已启用")
        run_metadata = langsmith.create_run_metadata(
            project_name=project_name,
            extra_info={
                "mode": "full" if not step_mode else "step",
                "step_level": step_level if step_mode else None,
                "human_review": need_human_review
            }
        )
    else:
        logger.info(f"[主图-调用] LangSmith tracing未启用")
        run_metadata = None

    logger.info(f"[主图-调用] 开始执行村庄规划: {project_name}")

    # 智能检测village_data是文件路径还是直接数据
    from ..tools.file_manager import VillageDataManager
    manager = VillageDataManager()

    # 如果看起来像文件路径，尝试加载
    if len(village_data) < 200 and ("\n" not in village_data or Path(village_data).exists()):
        try:
            result = manager.load_data(village_data)
            if result["success"]:
                village_data = result["content"]
                logger.info(f"[主图-调用] 从文件加载数据: {result['metadata'].get('filename', 'unknown')}, {len(village_data)} 字符")
        except:
            pass

    # 创建或使用提供的 OutputManager
    if output_manager is None:
        from ..utils.output_manager import create_output_manager
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
        "dimension_reports": {},
        "planning_concept": "",
        "concept_dimension_reports": {},
        "detailed_plan": "",
        "detailed_dimension_reports": {},
        "final_output": "",
        "output_manager": output_manager,
        "checkpoint_enabled": True,
        "last_checkpoint_id": "",
        "checkpoint_manager": None,
        "step_mode": step_mode,
        "step_level": step_level,
        "pause_after_step": step_mode,
        "quit_requested": False,
        "trigger_rollback": False,
        "rollback_target": "",
        "messages": []
    }

    # 初始化checkpoint工具（如果启用）
    if initial_state["checkpoint_enabled"]:
        checkpoint_manager = CheckpointTool(
            project_name=project_name,
            timestamp=output_manager.timestamp if output_manager else None
        )
        initial_state["checkpoint_manager"] = checkpoint_manager
        logger.info("[主图-调用] Checkpoint工具已初始化")

    try:
        if stream_mode:
            # 流式执行
            logger.info("[主图-调用] 使用流式模式")
            events = []
            for event in graph.stream(initial_state, stream_mode="values"):
                events.append(event)
                if "messages" in event and event["messages"]:
                    latest_msg = event["messages"][-1]
                    if hasattr(latest_msg, 'content'):
                        logger.info(f"[进度] {latest_msg.content[:100]}...")

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
        # 创建checkpoint工具
        checkpoint_manager = CheckpointTool(project_name)

        # 加载checkpoint
        load_result = checkpoint_manager.load(checkpoint_id)
        if not load_result["success"]:
            return {
                "success": False,
                "error": f"无法加载checkpoint: {checkpoint_id}"
            }

        state = load_result["state"]

        # 重建output_manager
        if output_manager is None:
            try:
                from ..utils.output_manager import create_output_manager
                output_manager = create_output_manager(
                    project_name=project_name
                )
            except Exception as e:
                logger.warning(f"[主图-恢复] 重建output_manager失败: {e}")

        # 获取当前层级
        current_layer = state.get("current_layer", 1)

        # 根据当前层级决定执行路径
        if current_layer == 2:
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
