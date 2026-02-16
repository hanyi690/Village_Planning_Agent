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

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Literal, TypedDict, Optional
from typing_extensions import Annotated
from langgraph.graph import StateGraph, END, START
from langgraph.graph.message import add_messages
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage

from ..core.config import (
    LLM_MODEL,
    MAX_TOKENS,
    DEFAULT_TASK_DESCRIPTION,
    DEFAULT_CONSTRAINTS,
    DEFAULT_ENABLE_REVIEW,
    DEFAULT_STREAM_MODE,
    DEFAULT_STEP_MODE,
)
from ..core.prompts import SYSTEM_PROMPT, PLANNING_CONCEPT_PROMPT
from ..core.dimension_config import DEFAULT_ADAPTER_CONFIG
from ..utils.logger import get_logger
from ..utils.output_manager import OutputManager
from ..utils.blackboard_manager import get_blackboard
from ..subgraphs.analysis_subgraph import call_analysis_subgraph
from ..subgraphs.concept_subgraph import call_concept_subgraph
from ..subgraphs.detailed_plan_subgraph import call_detailed_plan_subgraph

# 使用新工具
from ..tools.checkpoint_tool import CheckpointTool
from ..tools.revision_tool import RevisionTool
from ..utils.checkpoint_manager import get_checkpoint_manager

# 使用新的节点类
from ..nodes import (
    Layer1AnalysisNode,
    Layer2ConceptNode,
    Layer3DetailNode,
    ToolBridgeNode,
    PauseManagerNode
)

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

    # 会话管理
    session_id: str                # 会话ID（格式：YYYYMMDD_HHMMSS），用于唯一标识执行会话

    # 流程控制
    current_layer: int             # 当前执行层级 (1/2/3)
    previous_layer: int            # 上一层执行的编号 (用于判断刚完成哪一层)
    layer_1_completed: bool        # 现状分析完成
    layer_2_completed: bool        # 规划思路完成
    layer_3_completed: bool        # 详细规划完成

    # 人工审核
    need_human_review: bool        # 是否需要人工审核
    human_feedback: str            # 人工反馈
    need_revision: bool            # 是否需要修复

    # 各层成果
    analysis_report: str           # 现状分析报告
    analysis_dimension_reports: Dict[str, str]  # 各维度现状分析报告（用于部分状态传递）
    planning_concept: str          # 规划思路
    concept_dimension_reports: Dict[str, str]  # 各维度规划思路报告（用于部分状态传递）
    detailed_plan: str             # 详细规划方案
    detailed_dimension_reports: Dict[str, str]  # 各维度详细规划报告
    final_output: str              # 最终成果

    # 输出管理
    output_path: str  # 输出路径（可序列化的字符串，替代OutputManager对象）

    # Checkpoint相关
    checkpoint_enabled: bool       # 是否启用checkpoint
    last_checkpoint_id: str        # 最后保存的checkpoint ID

    # 逐步执行模式
    step_mode: bool                # 是否启用逐步执行模式
    step_level: str                # 步骤级别（layer/dimension/skill）
    pause_after_step: bool         # 是否在当前步骤后暂停
    # 注: 已删除 pending_review_layer，使用 previous_layer 表示待审查层级

    # 路由控制标志
    quit_requested: bool           # 用户请求退出
    trigger_rollback: bool         # 触发回退
    rollback_target: str           # 回退目标checkpoint ID

    # 错误处理
    execution_error: str           # 执行错误信息（用于前端显示）
    layer_1_failed_dimensions: List[str]  # Layer 1 失败的维度列表

    # 消息历史
    messages: Annotated[List[BaseMessage], add_messages]

    # 【新增】黑板模式数据共享
    blackboard: Dict[str, Any]  # 黑板数据共享
    # 格式：
    # {
    #     "raw_data_references": Dict[str, Any],  # 原始档案引用
    #     "tool_results": Dict[str, Any],         # 工具结果
    #     "shared_insights": List[Dict[str, Any]] # 共享洞察
    # }


# ==========================================
# LLM 辅助函数
# ==========================================

def _get_llm():
    """获取 LLM 实例，使用统一的 LLM 工厂"""
    from ..core.llm_factory import create_llm
    return create_llm(model=LLM_MODEL, temperature=0.7, max_tokens=MAX_TOKENS)


def _generate_simple_combined_report(
    project_name: str,
    dimension_reports: Dict[str, str],
    report_type: str,
    layer_number: int = 1
) -> str:
    """
    生成简单的综合报告（用于显示）

    【新增】简单拼接维度报告，不使用 LLM
    【更新】使用标准维度顺序（而非字母顺序）

    Args:
        project_name: 项目名称
        dimension_reports: 维度报告字典
        report_type: 报告类型（现状分析/规划思路/详细规划）
        layer_number: 层级编号 (1=现状分析, 2=规划思路, 3=详细规划)

    Returns:
        拼接后的综合报告
    """
    from ..utils.output_manager import OutputManager
    from ..core.dimension_config import (
        ANALYSIS_DIMENSION_NAMES,
        CONCEPT_DIMENSION_NAMES,
        DETAILED_DIMENSION_NAMES
    )

    report = f"# {project_name} {report_type}报告\n\n"

    # 获取维度名称映射
    if layer_number == 1:
        dimension_names_map = ANALYSIS_DIMENSION_NAMES()
    elif layer_number == 2:
        dimension_names_map = CONCEPT_DIMENSION_NAMES()
    elif layer_number == 3:
        dimension_names_map = DETAILED_DIMENSION_NAMES()
    else:
        dimension_names_map = {}

    # 使用标准顺序（而非字母顺序）
    standard_order = OutputManager._get_dimension_order(layer_number)

    for dimension_key in standard_order:
        if dimension_key not in dimension_reports:
            continue
        content = dimension_reports[dimension_key]
        display_name = dimension_names_map.get(dimension_key, dimension_key)

        # 检测内容是否已包含"## 标题"，如果有则直接使用
        if content.startswith("## "):
            report += f"{content}\n\n"
        else:
            report += f"## {display_name}\n\n{content}\n\n"

    report += f"---\n**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"

    return report


# ==========================================
# Layer执行节点
# ==========================================

def execute_layer1_analysis(state: VillagePlanningState) -> Dict[str, Any]:
    """
    Layer 1: 执行现状分析

    调用现状分析子图进行12个维度的并行分析。
    【重构】只保存维度报告，不生成综合报告
    【修复】检查失败维度，检测致命错误，防止不断弹窗
    """
    logger.info(f"[主图-Layer1] 开始现状分析，项目: {state['project_name']}")

    try:
        # 调用现状分析子图
        result = call_analysis_subgraph(
            raw_data=state["village_data"],
            project_name=state["project_name"]
        )

        # ✅ 新增：检测致命错误（连接失败等）
        error_msg = result.get("error", "")
        if error_msg and ("Connection error" in error_msg or "连接" in error_msg or "connection" in error_msg.lower()):
            logger.error(f"[主图-Layer1] 致命错误：LLM连接失败，终止执行")
            return {
                **state,
                "analysis_report": f"现状分析失败: {error_msg}",
                "analysis_dimension_reports": {},
                "layer_1_completed": False,
                "execution_error": "LLM服务连接失败，请检查网络或API配置",
                "quit_requested": True,  # 终止整个流程
                "messages": [AIMessage(content="LLM服务连接失败，请检查网络或API配置后重试。")]
            }

        # ✅ 新增：检查失败维度数量
        failed_dims = result.get("failed_dimensions", [])
        total_dims = 12  # 12个维度

        if failed_dims:
            logger.warning(f"[主图-Layer1] 有 {len(failed_dims)} 个维度分析失败: {failed_dims}")

            # 如果超过一半失败，视为致命错误
            if len(failed_dims) > total_dims // 2:
                logger.error(f"[主图-Layer1] 过多维度失败({len(failed_dims)}/{total_dims})，终止执行")
                return {
                    **state,
                    "analysis_report": f"现状分析失败: {len(failed_dims)}个维度无法完成",
                    "analysis_dimension_reports": {},
                    "layer_1_completed": False,
                    "execution_error": f"分析失败：{len(failed_dims)}个维度无法完成，请检查LLM配置或网络连接",
                    "quit_requested": True,  # 终止整个流程
                    "messages": [AIMessage(content=f"现状分析失败，{len(failed_dims)}个维度无法完成，请检查配置后重试。")]
                }

        if result["success"] or (len(failed_dims) <= total_dims // 2 and result.get("analysis_dimension_reports")):
            analysis_dimension_reports = result.get("analysis_dimension_reports", {})
            logger.info(f"[主图-Layer1] 现状分析完成，维度报告数量: {len(analysis_dimension_reports)}")

            # 【重构】从维度报告生成简单的综合报告（仅用于显示）
            combined_report = _generate_simple_combined_report(
                state["project_name"],
                analysis_dimension_reports,
                "现状分析",
                layer_number=1
            )

            # 如果有部分失败，在报告中标注
            if failed_dims:
                combined_report += f"\n\n---\n**注意**: {len(failed_dims)} 个维度分析失败: {', '.join(failed_dims)}"

            # 保存 Layer 1 结果（使用 OutputManager）
            from ..utils.output_manager_registry import get_output_manager_registry
            registry = get_output_manager_registry()
            output_manager = registry.get(state.get("session_id"))
            if output_manager and output_manager.use_default_structure:
                try:
                    save_result = output_manager.save_layer1_results(
                        combined_report=combined_report,
                        dimension_reports=analysis_dimension_reports
                    )
                    logger.info(f"[主图-Layer1] 保存了 {save_result['saved_count']} 个文件")
                except Exception as save_error:
                    logger.warning(f"[主图-Layer1] 保存结果时出错: {save_error}")

            # 保存checkpoint（如果启用）
            checkpoint_id = ""
            if state.get("checkpoint_enabled", False):
                checkpoint_manager = get_checkpoint_manager(
                    project_name=state["project_name"],
                    timestamp=state.get("session_id")
                )
                if checkpoint_manager:
                    save_result = checkpoint_manager.save(
                        state={**state, **{
                            "analysis_report": combined_report,
                            "analysis_dimension_reports": analysis_dimension_reports,
                            "layer_1_completed": True,
                            "current_layer": 2,
                            "layer_1_failed_dimensions": failed_dims
                        }},
                        layer=1,
                        description="Layer 1 现状分析完成"
                    )
                    checkpoint_id = save_result["checkpoint_id"] if save_result["success"] else ""

            return {
                "analysis_report": combined_report,
                "analysis_dimension_reports": analysis_dimension_reports,
                "layer_1_completed": True,
                "layer_1_failed_dimensions": failed_dims,
                "current_layer": 2,
                "previous_layer": 1,  # 刚完成的层级（也是待审查层级）
                "last_checkpoint_id": checkpoint_id,
                "messages": [AIMessage(content=f"现状分析完成，生成了 {len(analysis_dimension_reports)} 个维度的分析报告。")]
            }
        else:
            logger.error(f"[主图-Layer1] 现状分析失败: {result.get('error', '未知错误')}")
            return {
                "analysis_report": f"现状分析失败: {result.get('error', '未知错误')}",
                "analysis_dimension_reports": {},
                "layer_1_completed": False,
                "messages": [AIMessage(content="现状分析失败，请检查输入数据或稍后重试。")]
            }

    except Exception as e:
        logger.error(f"[主图-Layer1] 执行异常: {str(e)}")
        return {
            "analysis_report": f"执行异常: {str(e)}",
            "analysis_dimension_reports": {},
            "layer_1_completed": False,
            "messages": [AIMessage(content=f"现状分析过程中发生错误: {str(e)}")]
        }


def execute_layer2_concept(state: VillagePlanningState) -> Dict[str, Any]:
    """
    Layer 2: 生成规划思路（使用规划思路子图）

    调用规划思路子图进行4个维度的并行分析。
    【重构】只保存维度报告，不生成综合报告
    """
    logger.info(f"[主图-Layer2] 开始规划思路分析，项目: {state['project_name']}")

    try:
        # 调用规划思路子图（传递维度报告字典）
        result = call_concept_subgraph(
            project_name=state["project_name"],
            analysis_report=state["analysis_report"],
            dimension_reports=state.get("analysis_dimension_reports", {}),
            task_description=state["task_description"],
            constraints=state.get("constraints", "无特殊约束")
        )

        if result["success"]:
            concept_dimension_reports = result.get("concept_dimension_reports", {})
            logger.info(f"[主图-Layer2] 规划思路完成，维度报告数量: {len(concept_dimension_reports)}")

            # 【重构】从维度报告生成简单的综合报告（仅用于显示）
            combined_report = _generate_simple_combined_report(
                state["project_name"],
                concept_dimension_reports,
                "规划思路",
                layer_number=2
            )

            # 保存 Layer 2 结果（使用 OutputManager）
            from ..utils.output_manager_registry import get_output_manager_registry
            registry = get_output_manager_registry()
            output_manager = registry.get(state.get("session_id"))
            if output_manager and output_manager.use_default_structure:
                try:
                    save_result = output_manager.save_layer2_results(
                        combined_report=combined_report,
                        dimension_reports=concept_dimension_reports
                    )
                    logger.info(f"[主图-Layer2] 保存了 {save_result['saved_count']} 个文件")
                except Exception as save_error:
                    logger.warning(f"[主图-Layer2] 保存结果时出错: {save_error}")

            # 保存checkpoint（如果启用）
            checkpoint_id = ""
            if state.get("checkpoint_enabled", False):
                checkpoint_manager = get_checkpoint_manager(
                    project_name=state["project_name"],
                    timestamp=state.get("session_id")
                )
                if checkpoint_manager:
                    save_result = checkpoint_manager.save(
                        state={**state, **{
                            "planning_concept": combined_report,
                            "concept_dimension_reports": concept_dimension_reports,
                            "layer_2_completed": True,
                            "current_layer": 3
                        }},
                        layer=2,
                        description="Layer 2 规划思路完成"
                    )
                    checkpoint_id = save_result["checkpoint_id"] if save_result["success"] else ""

            return {
                "planning_concept": combined_report,
                "concept_dimension_reports": concept_dimension_reports,
                "layer_2_completed": True,
                "current_layer": 3,
                "previous_layer": 2,  # 刚完成的层级（也是待审查层级）
                "last_checkpoint_id": checkpoint_id,
                "messages": [AIMessage(content=f"规划思路已生成，包含 {len(concept_dimension_reports)} 个维度的分析报告。")]
            }
        else:
            logger.error(f"[主图-Layer2] 规划思路失败: {result.get('error', '未知错误')}")
            return {
                "planning_concept": f"规划思路失败: {result.get('error', '未知错误')}",
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

    调用详细规划子图进行12个专业维度的规划。
    【重构】只保存维度报告，不生成综合报告
    """
    logger.info(f"[主图-Layer3] 开始生成详细规划，项目: {state['project_name']}")

    try:
        # 调用详细规划子图（传递维度报告字典）
        result = call_detailed_plan_subgraph(
            project_name=state["project_name"],
            analysis_report=state["analysis_report"],
            planning_concept=state["planning_concept"],
            dimension_reports=state.get("analysis_dimension_reports", {}),
            concept_dimension_reports=state.get("concept_dimension_reports", {}),
            task_description=state.get("task_description", "制定村庄详细规划"),
            constraints=state.get("constraints", "无特殊约束"),
            required_dimensions=state.get("required_dimensions"),
            enable_human_review=state.get("need_human_review", False),
            # 新增：传递适配器配置
            enable_adapters=state.get("enable_adapters", False),
            adapter_config=state.get("adapter_config", {}),
            village_data=state.get("village_data", "")
        )

        if result["success"]:
            detailed_dimension_reports = result.get("detailed_dimension_reports", {})
            logger.info(f"[主图-Layer3] 详细规划完成，维度报告数量: {len(detailed_dimension_reports)}")
            logger.info(f"[主图-Layer3] 已完成维度: {result['completed_dimensions']}")

            # 【重构】从维度报告生成简单的综合报告（仅用于显示）
            combined_report = _generate_simple_combined_report(
                state["project_name"],
                detailed_dimension_reports,
                "详细规划",
                layer_number=3
            )

            # 保存 Layer 3 结果（使用 OutputManager）
            from ..utils.output_manager_registry import get_output_manager_registry
            registry = get_output_manager_registry()
            output_manager = registry.get(state.get("session_id"))
            if output_manager and output_manager.use_default_structure:
                try:
                    save_result = output_manager.save_layer3_results(
                        combined_report=combined_report,
                        dimension_reports=detailed_dimension_reports
                    )
                    logger.info(f"[主图-Layer3] 保存了 {save_result['saved_count']} 个文件")
                except Exception as save_error:
                    logger.warning(f"[主图-Layer3] 保存结果时出错: {save_error}")

            # 保存checkpoint（如果启用）
            checkpoint_id = ""
            if state.get("checkpoint_enabled", False):
                checkpoint_manager = get_checkpoint_manager(
                    project_name=state["project_name"],
                    timestamp=state.get("session_id")
                )
                if checkpoint_manager:
                    save_result = checkpoint_manager.save(
                        state={**state, **{
                            "detailed_plan": combined_report,
                            "detailed_dimension_reports": detailed_dimension_reports,
                            "layer_3_completed": True,
                            "current_layer": 4
                        }},
                        layer=3,
                        description="Layer 3 详细规划完成"
                    )
                    checkpoint_id = save_result["checkpoint_id"] if save_result["success"] else ""

            return {
                "detailed_plan": combined_report,
                "detailed_dimension_reports": detailed_dimension_reports,
                "layer_3_completed": True,
                "current_layer": 4,
                "previous_layer": 3,  # 刚完成的层级（也是待审查层级）
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
    from ..utils.output_manager_registry import get_output_manager_registry
    registry = get_output_manager_registry()
    output_manager = registry.get(state.get("session_id"))
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

    根据状态标志处理相应的工具逻辑：
    - need_human_review: 人工审查（返回暂停状态，等待 API 调用）
    - pause_after_step: 暂停交互（返回暂停状态，等待 API 调用）
    - need_revision: 修复（使用RevisionTool）

    Returns:
        更新后的状态字典
    """
    logger.info(f"[主图-工具桥接] 进入工具桥接节点")

    # 优先级：人工审查 > 暂停 > 修复
    if state.get("need_human_review", False):
        return _prepare_human_review(state)
    elif state.get("pause_after_step", False):
        return _prepare_pause(state)
    elif state.get("need_revision", False):
        return _run_revision(state)
    else:
        return state


def _prepare_human_review(state: VillagePlanningState) -> Dict[str, Any]:
    """
    准备人工审查（返回暂停状态）

    在Web环境中，我们无法直接进行交互式审查。
    相反，我们返回一个暂停状态，让API层知道需要人工审查。
    """
    logger.info(f"[主图-人工审查] 准备人工审查，返回暂停状态")

    current_layer = state.get("current_layer", 1)

    # 保存当前checkpoint以便恢复
    checkpoint_id = ""
    checkpoint_manager = get_checkpoint_manager(
        project_name=state["project_name"],
        timestamp=state.get("session_id")
    )
    if checkpoint_manager:
        save_result = checkpoint_manager.save(
            state=state,
            layer=current_layer,
            description=f"Layer {current_layer} 等待人工审查"
        )
        checkpoint_id = save_result.get("checkpoint_id", "") if save_result.get("success") else ""

    return {
        "pause_after_step": True,
        "messages": [AIMessage(content=f"Layer {current_layer} 已完成，等待人工审查")],
        "last_checkpoint_id": checkpoint_id
    }


def _prepare_pause(state: VillagePlanningState) -> Dict[str, Any]:
    """
    准备暂停（返回暂停状态）

    在step模式下，每一层完成后都会暂停，等待外部继续指令。
    """
    logger.info(f"[主图-暂停] Step模式暂停，返回暂停状态")

    current_layer = state.get("current_layer", 1)

    # 保存当前checkpoint以便恢复
    checkpoint_id = ""
    checkpoint_manager = get_checkpoint_manager(
        project_name=state["project_name"],
        timestamp=state.get("session_id")
    )
    if checkpoint_manager:
        # 保存当前状态
        save_result = checkpoint_manager.save(
            state=state,
            layer=current_layer,
            description=f"Layer {current_layer} 完成，step模式暂停"
        )
        checkpoint_id = save_result.get("checkpoint_id", "") if save_result.get("success") else ""

    return {
        "pause_after_step": True,
        "messages": [AIMessage(content=f"Layer {current_layer} 已完成，暂停中")],
        "last_checkpoint_id": checkpoint_id
    }


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

        # 使用共享的维度名称映射（用于显示）
        from ..core.dimension_config import DETAILED_DIMENSION_NAMES
        dimension_names = DETAILED_DIMENSION_NAMES()

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


# ==========================================
# 路由决策
# ==========================================

def route_after_pause(state: VillagePlanningState) -> Literal["layer1_analysis", "layer2_concept", "layer3_detail", "end"]:
    """
    pause节点后的路由：根据 previous_layer 决定执行还是终止
    
    使用 previous_layer 判断是否有刚完成的层级需要审查
    """
    current_layer = state.get("current_layer", 1)
    step_mode = state.get("step_mode", False)
    previous_layer = state.get("previous_layer", 0)
    
    # 如果有刚完成的层级（步进模式），终止执行等待批准
    if step_mode and previous_layer > 0:
        logger.info(f"[主图-路由] 步进模式：有待审查层级 {previous_layer}，终止执行等待批准")
        return "end"
    
    # 否则执行当前层级
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

    # 步进模式：进入tool_bridge准备暂停
    if state.get("step_mode", False):
        logger.info("[主图-路由] 步进模式：Layer 1完成，进入tool_bridge")
        return "tool_bridge"

    if state.get("need_human_review", False):
        logger.info("[主图-路由] 进入工具桥接（人工审核）")
        return "tool_bridge"

    # 非步进模式：直接进入下一层
    logger.info("[主图-路由] 直接进入规划思路阶段")
    return "layer2"


def route_after_layer2(state: VillagePlanningState) -> Literal["tool_bridge", "layer3", "end"]:
    """Layer 2 完成后的路由决策"""
    if not state["layer_2_completed"]:
        logger.warning("[主图-路由] 规划思路生成失败，流程终止")
        return "end"

    # 步进模式：进入tool_bridge准备暂停
    if state.get("step_mode", False):
        logger.info("[主图-路由] 步进模式：Layer 2完成，进入tool_bridge")
        return "tool_bridge"

    if state.get("need_human_review", False):
        logger.info("[主图-路由] 进入工具桥接（人工审核）")
        return "tool_bridge"

    # 非步进模式：直接进入下一层
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


def route_after_tool_bridge(state: VillagePlanningState) -> Literal["pause", "layer2_concept", "layer3_detail", "end", "__interrupt__"]:
    """
    工具桥接后的路由决策

    决定从tool_bridge出来后：
    - 如果waiting_for_review或__interrupt__：中断图执行
    - 如果step_mode开启且层级已完成：路由到pause节点（设置暂停）
    - 否则：直接路由到对应的layer执行节点

    ✅ 修复：使用 previous_layer 判断刚完成哪一层（而不是 current_layer）
    """
    # 检查中断信号（最高优先级）
    if state.get("__interrupt__", False) or state.get("waiting_for_review", False):
        logger.info("[主图-路由] 检测到中断信号，终止图执行")
        return "__interrupt__"

    # ✅ 修改：使用 previous_layer 判断刚完成哪一层
    previous_layer = state.get("previous_layer", 1)
    step_mode = state.get("step_mode", False)

    # Layer 1完成，步进模式：暂停
    if previous_layer == 1 and state.get("layer_1_completed", False) and step_mode:
        logger.info("[主图-路由] 步进模式：Layer 1完成，进入pause节点")
        return "pause"

    # Layer 1完成，非步进模式：进入Layer 2
    if previous_layer == 1 and state.get("layer_1_completed", False):
        logger.info("[主图-路由] 直接进入Layer 2")
        return "layer2_concept"

    # Layer 2完成，步进模式：暂停
    if previous_layer == 2 and state.get("layer_2_completed", False) and step_mode:
        logger.info("[主图-路由] 步进模式：Layer 2完成，进入pause节点")
        return "pause"

    # Layer 2完成，非步进模式：进入Layer 3
    if previous_layer == 2 and state.get("layer_2_completed", False):
        logger.info("[主图-路由] 直接进入Layer 3")
        return "layer3_detail"

    # Layer 3完成，生成最终成果
    if previous_layer == 3 and state.get("layer_3_completed", False):
        logger.info("[主图-路由] Layer 3完成，生成最终成果")
        return "end"

    # 检查退出标志
    if state.get("quit_requested", False):
        logger.info("[主图-路由] 用户请求退出，流程结束")
        return "end"

    # 检查回退标志
    if state.get("trigger_rollback", False):
        logger.info("[主图-路由] 触发回退，流程结束（由checkpoint_tool处理）")
        return "end"

    # 其他情况：根据previous_layer决定
    if previous_layer == 1:
        return "layer2_concept"
    elif previous_layer == 2:
        return "layer3_detail"
    else:
        return "end"


# ==========================================
# 构建主图
# ==========================================

def create_village_planning_graph(checkpointer: Optional[Any] = None) -> StateGraph:
    """
    创建村庄规划主图 (Main Graph)
    
    Args:
        checkpointer: AsyncSqliteSaver 实例 (必须显式传入)
    
    Returns:
        编译后的 StateGraph
    """
    logger.info("[主图构建] 开始构建村庄规划主图")
    
    # 强制类型检查(调试利器)
    logger.info(f"DEBUG: 传入的 checkpointer 类型是: {type(checkpointer)}")
    logger.info(f"DEBUG: checkpointer 类名是: {type(checkpointer).__name__}")
    logger.info(f"DEBUG: checkpointer MRO: {[cls.__name__ for cls in type(checkpointer).__mro__]}")
    logger.info(f"DEBUG: checkpointer repr: {repr(checkpointer)}")
    
    # 如果类型不对,打印调用栈,看看是谁在传错东西
    if "ContextManager" in str(type(checkpointer)):
        import traceback
        logger.error("发现元凶：传入了 ContextManager 而不是 Saver 实例！")
        logger.error("调用栈:")
        traceback.print_stack()
        raise TypeError("发现元凶：传入了 ContextManager 而不是 Saver 实例！")
    
    # 强制要求外部传入 checkpointer,不要使用默认值
    if checkpointer is None:
        raise ValueError("Checkpointer 必须显式传入！不能为 None")
    
    # 在这里加一个断言,如果类型不对直接报错,防止它进入 compile
    from langgraph.checkpoint.base import BaseCheckpointSaver
    if not isinstance(checkpointer, BaseCheckpointSaver):
        raise TypeError(
            f"这就是元凶！拿到的 checkpointer 类型居然是: {type(checkpointer)} "
            f"(类名: {type(checkpointer).__name__})"
        )

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
            "layer3_detail": "layer3_detail",
            "end": END  # ✅ 添加：支持步进模式暂停时终止执行
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

    # tool_bridge -> pause/layer2/layer3/end/__interrupt__
    # 在step模式下，tool_bridge会路由到pause节点以重置暂停状态
    builder.add_conditional_edges(
        "tool_bridge",
        route_after_tool_bridge,
        {
            "pause": "pause",
            "layer2_concept": "layer2_concept",
            "layer3_detail": "layer3_detail",
            "__interrupt__": END,  # NEW: Route interruption to END
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

    # Compile with checkpointer
    if checkpointer is None:
        # 如果没有提供 checkpointer,使用 MemorySaver (用于旧代码兼容)
        from langgraph.checkpoint.memory import MemorySaver
        checkpointer = MemorySaver()
        logger.info("[主图构建] Using MemorySaver checkpointer (in-memory, no persistence)")
    else:
        # 在这里加一个断言,如果类型不对直接报错,防止它进入 compile
        from langgraph.checkpoint.base import BaseCheckpointSaver
        if not isinstance(checkpointer, BaseCheckpointSaver):
            raise TypeError(
                f"这就是元凶！拿到的 checkpointer 类型居然是: {type(checkpointer)} "
                f"(类名: {type(checkpointer).__name__})"
            )
        logger.info(f"[主图构建] Using provided checkpointer: {type(checkpointer).__name__}")
    
    main_graph = builder.compile(checkpointer=checkpointer)

    logger.info("[主图构建] 村庄规划主图构建完成 (with checkpointer)")

    return main_graph


# ==========================================
# 对外接口
# ==========================================

def run_village_planning(
    project_name: str,
    village_data: str,
    task_description: str = DEFAULT_TASK_DESCRIPTION,
    constraints: str = DEFAULT_CONSTRAINTS,
    need_human_review: bool = DEFAULT_ENABLE_REVIEW,
    stream_mode: bool = DEFAULT_STREAM_MODE,
    output_manager: OutputManager = None,
    custom_output_path: str = None,
    step_mode: bool = DEFAULT_STEP_MODE,
    step_level: str = "layer",
    resume_from_checkpoint: str = None
) -> Dict[str, Any]:
    """
    执行村庄规划主流程

    支持的分步执行模式：
    - step_mode=False: 一次性执行完成所有层级
    - step_mode=True: 每层完成后暂停，返回暂停状态

    支持从checkpoint恢复：
    - resume_from_checkpoint: 指定checkpoint ID，从该点继续执行

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
        resume_from_checkpoint: checkpoint ID（用于恢复执行）

    Returns:
        包含最终成果或暂停状态的字典
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

    # 从checkpoint恢复（如果提供）
    if resume_from_checkpoint:
        logger.info(f"[主图-调用] 从checkpoint恢复: {resume_from_checkpoint}")
        checkpoint_manager = get_checkpoint_manager(
            project_name=project_name,
            timestamp=output_manager.timestamp if output_manager else None
        )
        load_result = checkpoint_manager.load(resume_from_checkpoint)

        if load_result["success"]:
            initial_state = load_result["state"]
            logger.info(f"[主图-调用] 已恢复到 Layer {initial_state.get('current_layer', 1)}")
        else:
            logger.error(f"[主图-调用] 无法加载checkpoint: {load_result.get('error')}")
            return {
                "success": False,
                "error": f"无法加载checkpoint: {load_result.get('error')}"
            }
    else:
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

    # 注册到全局registry
    from ..utils.output_manager_registry import get_output_manager_registry
    registry = get_output_manager_registry()
    session_id = output_manager.timestamp if output_manager else datetime.now().strftime("%Y%m%d_%H%M%S")
    registry.register(session_id, output_manager)

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
        "session_id": session_id,
        "current_layer": 1,
        "previous_layer": 1,  # ✅ 新增：初始化为1
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
        "output_path": str(output_manager.output_path) if output_manager else "",
        "checkpoint_enabled": True,
        "last_checkpoint_id": "",
        "step_mode": step_mode,
        "step_level": step_level,
        "pause_after_step": step_mode,
        "quit_requested": False,
        "trigger_rollback": False,
        "rollback_target": "",
        "execution_error": "",  # 新增：执行错误信息
        "layer_1_failed_dimensions": [],  # 新增：Layer 1 失败的维度
        "messages": [],
        # 新增：黑板管理器
        "blackboard": get_blackboard(),
        # 适配器配置（使用共享的默认配置）
        "enable_adapters": False,
        "adapter_config": DEFAULT_ADAPTER_CONFIG
    }

    # 初始化checkpoint工具（如果启用）
    if initial_state["checkpoint_enabled"]:
        checkpoint_manager = get_checkpoint_manager(
            project_name=project_name,
            timestamp=output_manager.timestamp if output_manager else None
        )
        logger.info("[主图-调用] Checkpoint工具已初始化（通过全局管理器）")
        # 不将 checkpoint_manager 添加到 initial_state

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

        # 检查是否处于暂停状态
        if final_state.get("pause_after_step", False):
            current_layer = final_state.get("current_layer", 1)
            logger.info(f"[主图-调用] 任务暂停在 Layer {current_layer}")

            return {
                "success": True,
                "status": "paused",
                "current_layer": current_layer,
                "checkpoint_id": final_state.get("last_checkpoint_id", ""),
                "analysis_report": final_state.get("analysis_report", ""),
                "planning_concept": final_state.get("planning_concept", ""),
                "detailed_plan": final_state.get("detailed_plan", ""),
                "layer_1_completed": final_state.get("layer_1_completed", False),
                "layer_2_completed": final_state.get("layer_2_completed", False),
                "layer_3_completed": final_state.get("layer_3_completed", False),
                "output_manager": output_manager,
                "state": final_state  # 返回完整状态用于恢复
            }

        # 正常完成
        return {
            "success": True,
            "status": "completed",
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
            "output_manager": output_manager,
            "state": final_state
        }

    except Exception as e:
        logger.error(f"[主图-调用] 执行失败: {str(e)}")
        return {
            "success": False,
            "status": "failed",
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
        checkpoint_manager = get_checkpoint_manager(
            project_name=project_name,
            timestamp=output_manager.timestamp if output_manager else None
        )

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

        # 注册到全局registry
        from ..utils.output_manager_registry import get_output_manager_registry
        registry = get_output_manager_registry()
        session_id = state.get("session_id")
        if session_id:
            registry.register(session_id, output_manager)

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
            state["output_path"] = str(output_manager.output_path) if output_manager else ""
            state["checkpoint_enabled"] = True

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
            state["output_path"] = str(output_manager.output_path) if output_manager else ""
            state["checkpoint_enabled"] = True

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
