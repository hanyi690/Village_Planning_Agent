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
from ..utils.blackboard_manager import get_blackboard
from ..subgraphs.analysis_subgraph import call_analysis_subgraph
from ..subgraphs.concept_subgraph import call_concept_subgraph
from ..subgraphs.detailed_plan_subgraph import call_detailed_plan_subgraph

# 使用新工具（CheckpointTool 已移除，统一使用 LangGraph AsyncSqliteSaver）
from ..tools.revision_tool import RevisionTool

# 使用新的节点类
from ..nodes import (
    Layer1AnalysisNode,
    Layer2ConceptNode,
    Layer3DetailNode,
    ToolBridgeNode
)
from ..nodes.tool_nodes import _run_revision

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
    revision_target_dimensions: List[str]  # 用户选择的修复维度列表

    # 各层成果（统一命名：analysis_reports, concept_reports, detail_reports）
    # 综合报告已移除，改为动态生成以节省存储空间
    analysis_reports: Dict[str, str]  # Layer 1: 各维度现状分析报告
    concept_reports: Dict[str, str]   # Layer 2: 各维度规划思路报告
    detail_reports: Dict[str, str]    # Layer 3: 各维度详细规划报告
    final_output: str              # 最终成果

    # 输出管理
    output_manager: OutputManager  # 输出管理器实例

    # Checkpoint相关（由 LangGraph AsyncSqliteSaver 自动管理）
    last_checkpoint_id: str        # 最后保存的checkpoint ID

    # 逐步执行模式
    step_mode: bool                # 是否启用逐步执行模式
    step_level: str                # 步骤级别（layer/dimension/skill）
    pause_after_step: bool         # 是否在当前步骤后暂停
    previous_layer: int            # 刚完成的层级编号（用于暂停逻辑）

    # 路由控制标志
    quit_requested: bool           # 用户请求退出
    trigger_rollback: bool         # 触发回退
    rollback_target: str           # 回退目标checkpoint ID

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

    # 【新增】修订历史 - 保留每一次修改的完整记录
    revision_history: List[Dict[str, Any]]  # 修订历史
    # 格式: [{dimension, layer, old_content, new_content, feedback, timestamp}]

    # 【新增】最近修复的维度列表 - 用于 SSE 事件触发
    last_revised_dimensions: List[str]  # 最近一次修复涉及的维度列表

    # 【新增】RAG 知识缓存 - 预加载模式下的知识上下文缓存
    knowledge_cache: Dict[str, str]  # 维度 -> 知识上下文
    # 格式: {"land_use": "知识内容...", "infrastructure": "知识内容..."}


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

            # Checkpoint 由 LangGraph 自动保存，无需手动处理

            return {
                "analysis_reports": result.get("analysis_reports", {}),
                "layer_1_completed": True,
                "current_layer": 2,
                "messages": [AIMessage(content=f"现状分析完成，生成了 {len(result.get('analysis_reports', {}))} 个维度报告。")]
            }
        else:
            logger.error(f"[主图-Layer1] 现状分析失败: {result.get('analysis_reports', {})}")
            return {
                "analysis_reports": {},
                "layer_1_completed": False,
                "messages": [AIMessage(content="现状分析失败，请检查输入数据或稍后重试。")]
            }

    except Exception as e:
        logger.error(f"[主图-Layer1] 执行异常: {str(e)}")
        return {
            "analysis_reports": {},
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
            analysis_reports=state.get("analysis_reports", {}),
            task_description=state["task_description"],
            constraints=state.get("constraints", "无特殊约束")
        )

        if result["success"]:
            logger.info(f"[主图-Layer2] 规划思路完成，报告数: {len(result.get('concept_reports', {}))}")

            # 保存 Layer 2 结果（使用 OutputManager）
            output_manager: OutputManager = state.get("output_manager")
            if output_manager and output_manager.use_default_structure:
                try:
                    save_result = output_manager.save_layer2_results(
                        combined_report=result.get("concept_report", ""),
                        dimension_reports=result.get("concept_reports", {})
                    )
                    logger.info(f"[主图-Layer2] 保存了 {save_result['saved_count']} 个文件")
                except Exception as save_error:
                    logger.warning(f"[主图-Layer2] 保存结果时出错: {save_error}")

            # Checkpoint 由 LangGraph 自动保存，无需手动处理

            return {
                "concept_reports": result.get("concept_reports", {}),
                "layer_2_completed": True,
                "current_layer": 3,
                "messages": [AIMessage(content=f"规划思路已生成，包含 {len(result.get('concept_reports', {}))} 个维度报告。")]
            }
        else:
            logger.error(f"[主图-Layer2] 规划思路失败: {result.get('concept_report', '')}")
            return {
                "concept_reports": {},
                "layer_2_completed": False,
                "messages": [AIMessage(content="规划思路生成失败，请检查输入数据或稍后重试。")]
            }

    except Exception as e:
        logger.error(f"[主图-Layer2] 执行异常: {str(e)}")
        return {
            "concept_reports": {},
            "layer_2_completed": False,
            "messages": [AIMessage(content=f"规划思路生成过程中发生错误: {str(e)}")]
        }


def execute_layer3_detail(state: VillagePlanningState) -> Dict[str, Any]:
    """
    Layer 3: 详细规划

    调用详细规划子图进行10个专业维度的规划。
    新增：支持适配器配置。
    """
    logger.info(f"[主图-Layer3] 开始生成详细规划，项目: {state['project_name']}")

    try:
        # 调用详细规划子图（传递维度报告字典）
        result = call_detailed_plan_subgraph(
            project_name=state["project_name"],
            analysis_reports=state.get("analysis_reports", {}),
            concept_reports=state.get("concept_reports", {}),
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
            logger.info(f"[主图-Layer3] 详细规划完成，报告数: {len(result.get('detail_reports', {}))}")
            logger.info(f"[主图-Layer3] 已完成维度: {result['completed_dimensions']}")

            # 直接使用子图返回的 detail_reports
            detail_reports = result.get("detail_reports", {})

            # 保存 Layer 3 结果（使用 OutputManager）
            output_manager: OutputManager = state.get("output_manager")
            if output_manager and output_manager.use_default_structure:
                try:
                    # 动态生成汇总报告
                    from ..utils.report_utils import generate_detail_report
                    combined_report = generate_detail_report(detail_reports, state.get("project_name", "村庄"))
                    
                    save_result = output_manager.save_layer3_results(
                        combined_report=combined_report,
                        dimension_reports=detail_reports
                    )
                    logger.info(f"[主图-Layer3] 保存了 {save_result['saved_count']} 个文件")
                except Exception as save_error:
                    logger.warning(f"[主图-Layer3] 保存结果时出错: {save_error}")

            # Checkpoint 由 LangGraph 自动保存，无需手动处理

            return {
                "detail_reports": detail_reports,
                "layer_3_completed": True,
                "current_layer": 4,
                "messages": [AIMessage(content=f"详细规划已生成，包含 {len(result['completed_dimensions'])} 个专业维度。")]
            }
        else:
            logger.error(f"[主图-Layer3] 详细规划失败: {result.get('error', '未知错误')}")
            return {
                "detail_reports": {},
                "layer_3_completed": False,
                "messages": [AIMessage(content="详细规划生成失败，请检查输入数据或稍后重试。")]
            }

    except Exception as e:
        logger.error(f"[主图-Layer3] 执行异常: {str(e)}")
        return {
            "detail_reports": {},
            "layer_3_completed": False,
            "messages": [AIMessage(content=f"详细规划过程中发生错误: {str(e)}")]
        }


def generate_final_output(state: VillagePlanningState) -> Dict[str, Any]:
    """
    生成最终规划成果

    整合三层输出，动态生成完整的规划文档。
    """
    logger.info(f"[主图-成果] 开始生成最终成果，项目: {state['project_name']}")
    
    # 动态生成各层综合报告
    from ..utils.report_utils import (
        generate_analysis_report,
        generate_concept_report,
        generate_detail_report
    )
    
    project_name = state['project_name']
    
    analysis_report = generate_analysis_report(
        state.get("analysis_reports", {}),
        project_name
    )
    
    planning_concept = generate_concept_report(
        state.get("concept_reports", {}),
        project_name
    )
    
    detailed_plan = generate_detail_report(
        state.get("detail_reports", {}),
        project_name
    )

    final_output = f"""
# {project_name} 村庄规划成果

---

## 一、现状分析报告

{analysis_report}

---

## 二、规划思路

{planning_concept}

---

## 三、详细规划方案

{detailed_plan}

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
    """
    执行人工审查（Web版本）
    
    注意：在Web环境中，人工审查由前端ReviewDrawer组件处理。
    此函数仅设置审查请求状态，等待前端响应。
    """
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

    # 获取可用checkpoint列表（由前端从后端 API 获取，这里不再处理）

    # 创建审查请求（非阻塞，等待前端响应）
    from ..tools.web_review_tool import WebReviewTool
    tool = WebReviewTool()
    session_id = state.get("session_id", "default")
    
    result = tool.request_review(
        content=content,
        title=title,
        session_id=session_id,
        current_layer=current_layer,
        available_checkpoints=[]  # 前端从 API 获取
    )

    if result["success"]:
        logger.info(f"[主图-人工审查] 已创建审查请求: {result['review_id']}")
        return {
            "messages": [AIMessage(content=f"已创建审查请求: {result['review_id']}")],
            "review_id": result["review_id"],
            "waiting_for_review": True
        }
    else:
        logger.warning("[主图-人工审查] 创建审查请求失败，默认通过")
        return {
            "messages": [AIMessage(content="审查请求创建失败，默认通过")],
            "need_human_review": False
        }


def _run_pause_interaction(state: VillagePlanningState) -> Dict[str, Any]:
    """
    执行暂停交互（Web版本）
    
    注意：在Web环境中，暂停交互由前端处理。
    此函数仅设置暂停状态标志，等待前端指令。
    """
    logger.info(f"[主图-暂停] 进入暂停节点")

    # Preserve layer completion state
    preserved_state = {
        "layer_1_completed": state.get("layer_1_completed", False),
        "layer_2_completed": state.get("layer_2_completed", False),
        "layer_3_completed": state.get("layer_3_completed", False),
        "current_layer": state.get("current_layer", 1),
    }

    # 在Web环境中，暂停交互由前端处理
    return {
        "pause_after_step": True,
        "messages": [AIMessage(content="已暂停，等待前端指令")],
        **preserved_state
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
        detail_reports = state.get("detail_reports", {})

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
        updated_detailed_plan = ""
        for dimension, revised_result in revised_results.items():
            dimension_name = dimension_names.get(dimension, dimension)
            updated_detailed_plan += f"\n\n## 修复后的{dimension_name}\n\n{revised_result}"
            # 同时更新状态中的维度报告
            detail_reports[dimension] = revised_result

        return {
            "detail_reports": detail_reports,
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
# 暂停初始化函数（替代 PauseManagerNode）
# ==========================================

def init_pause_state(state: VillagePlanningState) -> Dict[str, Any]:
    """
    初始化暂停状态
    
    只在 previous_layer > 0 且 step_mode 启用时设置暂停。
    流程开始时（previous_layer=0）不暂停。
    
    修复流程（need_revision=True）时清除暂停标志，让修复正常执行。
    """
    # 修复流程不需要暂停，清除暂停标志
    if state.get("need_revision", False):
        logger.info("[主图-暂停初始化] need_revision=True，清除 pause_after_step 让修复流程正常执行")
        return {"pause_after_step": False}
    
    if state.get("step_mode", False) and state.get("previous_layer", 0) > 0:
        logger.info(f"[主图-暂停初始化] Step模式 + Layer {state.get('previous_layer')} 完成，设置pause_after_step=True")
        return {"pause_after_step": True}
    return {}


# ==========================================
# 路由决策
# ==========================================

def route_after_pause(state: VillagePlanningState) -> Literal["tool_bridge", "layer1_analysis", "layer2_concept", "layer3_detail", "generate_final"]:
    """
    pause节点后的路由：先检查修复标志，再根据current_layer决定执行哪个layer

    优先级：need_revision > current_layer
    """
    # 优先检查修复标志
    if state.get("need_revision", False):
        logger.info("[主图-路由] 检测到 need_revision=True，路由到 tool_bridge 执行修复")
        return "tool_bridge"
    
    # 正常路由到当前层
    current_layer = state.get("current_layer", 1)
    logger.info(f"[主图-路由] 从pause节点路由到Layer {current_layer}")

    if current_layer == 1:
        return "layer1_analysis"
    elif current_layer == 2:
        return "layer2_concept"
    elif current_layer == 3:
        return "layer3_detail"
    elif current_layer == 4:
        # Layer 3 审查通过后，从 pause 路由到最终成果生成
        logger.info("[主图-路由] Layer 3 审查通过，从pause路由到最终成果生成")
        return "generate_final"
    else:
        # 默认返回layer1
        logger.warning(f"[主图-路由] 无效的current_layer: {current_layer}，默认路由到Layer 1")
        return "layer1_analysis"


def route_after_layer1(state: VillagePlanningState) -> Literal["tool_bridge", "layer2", "end"]:
    """Layer 1 完成后的路由决策"""
    if not state["layer_1_completed"]:
        logger.warning("[主图-路由] 现状分析失败，流程终止")
        return "end"

    # 检查是否需要暂停（step_mode + previous_layer > 0）
    if state.get("step_mode", False) and state.get("previous_layer", 0) > 0:
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

    # 检查是否需要暂停（step_mode + previous_layer > 0）
    if state.get("step_mode", False) and state.get("previous_layer", 0) > 0:
        logger.info("[主图-路由] 进入工具桥接（暂停）")
        return "tool_bridge"

    if state.get("need_human_review", False):
        logger.info("[主图-路由] 进入工具桥接（人工审核）")
        return "tool_bridge"

    logger.info("[主图-路由] 进入详细规划阶段")
    return "layer3"


def route_after_layer3(state: VillagePlanningState) -> Literal["tool_bridge", "final", "end"]:
    """Layer 3 完成后的路由决策"""
    if not state["layer_3_completed"]:
        logger.warning("[主图-路由] 详细规划失败，流程终止")
        return "end"

    # 检查是否需要暂停（step_mode + previous_layer > 0）
    if state.get("step_mode", False) and state.get("previous_layer", 0) > 0:
        logger.info("[主图-路由] Layer 3 完成，进入工具桥接（暂停）")
        return "tool_bridge"

    if state.get("need_human_review", False):
        logger.info("[主图-路由] 进入工具桥接（人工审核）")
        return "tool_bridge"

    logger.info("[主图-路由] 进入最终成果生成")
    return "final"


def route_after_tool_bridge(state: VillagePlanningState) -> Literal["init_pause", "layer2_concept", "layer3_detail", "generate_final", "end"]:
    """
    工具桥接后的路由决策

    决定从tool_bridge出来后：
    - 如果step_mode开启：路由到init_pause节点（设置暂停状态）
    - 否则：直接路由到对应的layer执行节点
    - Layer 3 审查后：路由到 generate_final 生成最终成果
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
                logger.info("[主图-路由] Step模式：tool_bridge → init_pause → layer2")
                return "init_pause"
            return "layer2_concept"
        elif current_layer == 2:
            if state.get("step_mode", False):
                logger.info("[主图-路由] Step模式：tool_bridge → init_pause → layer3")
                return "init_pause"
            return "layer3_detail"
        else:
            return "end"

    # 根据current_layer和step_mode决定下一步
    if current_layer == 1:
        # Layer 1: 从tool_bridge回到layer 1（通常是回退后）或进入layer 2
        if state.get("step_mode", False):
            logger.info("[主图-路由] Step模式：tool_bridge → init_pause → layer2")
            return "init_pause"
        logger.info("[主图-路由] 直接进入Layer 2")
        return "layer2_concept"
    elif current_layer == 2:
        # Layer 2: 从tool_bridge继续到layer 2
        if state.get("step_mode", False):
            logger.info("[主图-路由] Step模式：tool_bridge → init_pause → layer2")
            return "init_pause"
        logger.info("[主图-路由] 直接进入Layer 2")
        return "layer2_concept"
    elif current_layer == 3:
        # Layer 3: 从tool_bridge继续到layer 3
        if state.get("step_mode", False):
            logger.info("[主图-路由] Step模式：tool_bridge → init_pause → layer3")
            return "init_pause"
        logger.info("[主图-路由] 直接进入Layer 3")
        return "layer3_detail"
    elif current_layer == 4:
        # Layer 3 审查通过后，进入最终成果生成
        if state.get("step_mode", False):
            logger.info("[主图-路由] Step模式：tool_bridge → init_pause → final")
            return "init_pause"
        logger.info("[主图-路由] Layer 3 审查通过，进入最终成果生成")
        return "generate_final"
    else:
        logger.info("[主图-路由] 流程结束")
        return "end"


# ==========================================
# 构建主图
# ==========================================

def create_village_planning_graph(checkpointer=None) -> StateGraph:
    """
    创建村庄规划主图

    使用新的节点类实例替代旧的函数节点。

    Args:
        checkpointer: LangGraph checkpointer 实例（如 AsyncSqliteSaver），
                     用于持久化图执行状态，支持暂停/恢复功能

    Returns:
        编译后的 StateGraph 实例
    """
    logger.debug("[主图构建] 开始构建村庄规划主图")  # 改为 DEBUG 级别减少日志噪音

    # 创建节点实例
    layer1_node = Layer1AnalysisNode()
    layer2_node = Layer2ConceptNode()
    layer3_node = Layer3DetailNode()
    tool_bridge_node = ToolBridgeNode()

    builder = StateGraph(VillagePlanningState)

    # 添加节点
    builder.add_node("init_pause", init_pause_state)  # 简化的暂停初始化
    builder.add_node("layer1_analysis", layer1_node)
    builder.add_node("layer2_concept", layer2_node)
    builder.add_node("layer3_detail", layer3_node)
    builder.add_node("generate_final", generate_final_output)
    builder.add_node("tool_bridge", tool_bridge_node)

    # 构建执行流程
    # START -> init_pause (初始化暂停状态)
    builder.add_edge(START, "init_pause")

    # pause -> 根据current_layer路由到对应的layer，或路由到tool_bridge执行修复
    builder.add_conditional_edges(
        "init_pause",
        route_after_pause,
        {
            "tool_bridge": "tool_bridge",
            "layer1_analysis": "layer1_analysis",
            "layer2_concept": "layer2_concept",
            "layer3_detail": "layer3_detail",
            "generate_final": "generate_final"
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

    # tool_bridge -> pause/layer2/layer3/generate_final/end
    # 在step模式下，tool_bridge会路由到pause节点以重置暂停状态
    builder.add_conditional_edges(
        "tool_bridge",
        route_after_tool_bridge,
        {
            "init_pause": "init_pause",
            "layer2_concept": "layer2_concept",
            "layer3_detail": "layer3_detail",
            "generate_final": "generate_final",
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

    # Layer 3 -> tool_bridge/final/end
    builder.add_conditional_edges(
        "layer3_detail",
        route_after_layer3,
        {
            "tool_bridge": "tool_bridge",
            "final": "generate_final",
            "end": END
        }
    )

    # 最终节点 -> END
    builder.add_edge("generate_final", END)

    # 编译主图（支持 checkpointer 持久化）
    main_graph = builder.compile(checkpointer=checkpointer)

    logger.debug("[主图构建] 村庄规划主图构建完成")  # 改为 DEBUG 级别减少日志噪音

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
        "analysis_reports": {},
        "concept_reports": {},
        "detail_reports": {},
        "final_output": "",
        "output_manager": output_manager,
        "last_checkpoint_id": "",
        "step_mode": step_mode,
        "step_level": step_level,
        "pause_after_step": step_mode,
        "quit_requested": False,
        "trigger_rollback": False,
        "rollback_target": "",
        "messages": [],
        # 新增：黑板管理器
        "blackboard": get_blackboard(),
        # 新增：适配器配置
        "enable_adapters": False,  # 默认关闭适配器
        "adapter_config": {
            # 配置每个维度使用的适配器
            "industry": ["gis"],  # 产业规划使用GIS分析
            "ecological": ["gis"],  # 生态规划使用GIS分析
            "traffic": ["network"],  # 交通规划使用网络分析
            "infrastructure": ["gis", "network"],  # 基础设施使用多种适配器
            "public_service": ["network"],  # 公共服务使用网络分析
            "master_plan": ["gis"],  # 总体规划使用GIS分析
            "landscape": ["gis"],  # 风貌规划使用GIS分析
            "disaster_prevention": ["gis"]  # 防灾减灾使用GIS分析
        }
    }

    # Checkpoint 由 LangGraph AsyncSqliteSaver 自动管理，无需手动初始化

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
    output_manager: OutputManager = None,
    checkpointer = None
) -> Dict[str, Any]:
    """
    从checkpoint恢复执行（使用 LangGraph AsyncSqliteSaver）

    Args:
        checkpoint_id: checkpoint ID
        project_name: 项目名称
        output_manager: 输出管理器（可选）
        checkpointer: LangGraph checkpointer 实例（可选）

    Returns:
        执行结果字典
    """
    logger.info(f"[主图-恢复] 从checkpoint恢复: {checkpoint_id}")

    try:
        # 获取 checkpointer（如果未提供）
        if checkpointer is None:
            import asyncio
            from backend.api.planning import get_global_checkpointer
            
            checkpointer = asyncio.run(get_global_checkpointer())

        # 创建主图
        graph = create_village_planning_graph(checkpointer=checkpointer)

        # 构建配置（使用 project_name 作为 thread_id）
        config = {
            "configurable": {
                "thread_id": project_name,
                "checkpoint_id": checkpoint_id
            }
        }

        # 重建 output_manager
        if output_manager is None:
            try:
                from ..utils.output_manager import create_output_manager
                output_manager = create_output_manager(
                    project_name=project_name
                )
            except Exception as e:
                logger.warning(f"[主图-恢复] 重建output_manager失败: {e}")

        # 确保输出目录存在
        if output_manager:
            output_manager.ensure_directories()

        # 从指定 checkpoint 继续执行
        # LangGraph 会自动从 checkpoint_id 恢复状态
        final_state = graph.invoke(None, config)

        logger.info("[主图-恢复] 从checkpoint恢复执行完成")

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
