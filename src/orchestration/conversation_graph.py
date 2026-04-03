"""
对话式规划图 (Conversation Graph)

实现多轮对话式规划交互：
- 用户可随时提问、调整、确认
- 意图路由决定下一步动作
- 支持工具调用、规划执行、问答等模式

与 main_graph.py 的关系：
- main_graph.py: 任务执行型，三层线性流程
- conversation_graph.py: 对话型，循环交互流程
"""

from typing import Dict, Any, List, Optional
from langgraph.graph import StateGraph, END, START
from langgraph.graph.message import add_messages
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage

from .main_graph import ConversationState, PlanningPhase, PlanningContext
from .intent_classifier import classify_intent, UserIntent
from ..core.llm_factory import create_llm
from ..core.config import LLM_MODEL, MAX_TOKENS
from ..utils.logger import get_logger

logger = get_logger(__name__)


# ==========================================
# 对话节点实现
# ==========================================

def conversation_node(state: ConversationState) -> Dict[str, Any]:
    """
    主对话节点 - 处理用户输入并生成响应

    根据当前阶段和用户意图，生成合适的响应。
    可能包含工具调用请求。
    """
    messages = state["messages"]
    phase = state.get("current_phase", PlanningPhase.INIT.value)

    # 获取 LLM
    llm = create_llm(model=LLM_MODEL, temperature=0.7, max_tokens=MAX_TOKENS)

    # 构建系统提示
    system_prompt = _build_system_prompt(state)

    # 准备消息
    full_messages = [SystemMessage(content=system_prompt)] + list(messages)

    # 生成响应
    response = llm.invoke(full_messages)

    return {
        "messages": [response],
        "conversation_turns": state.get("conversation_turns", 0) + 1
    }


def tool_execution_node(state: ConversationState) -> Dict[str, Any]:
    """
    工具执行节点 - 执行工具调用

    从最后一条 AI 消息中提取工具调用请求并执行。
    发送 SSE 事件用于前端可视化。
    """
    from ..tools.registry import ToolRegistry
    from backend.api.planning import (
        append_tool_call_event,
        append_tool_result_event
    )
    from ..tools.adapters.tool_wrapper import TOOL_DISPLAY_NAMES

    messages = state["messages"]
    session_id = state["session_id"]

    # 获取最后一条 AI 消息
    last_message = messages[-1] if messages else None
    if not last_message or not hasattr(last_message, "tool_calls"):
        return {"messages": []}

    tool_calls = getattr(last_message, "tool_calls", [])
    if not tool_calls:
        return {"messages": []}

    tool_results = []

    for tool_call in tool_calls:
        tool_name = tool_call.get("name", tool_call.get("function", {}).get("name", ""))
        tool_args = tool_call.get("args", tool_call.get("function", {}).get("arguments", {}))

        display_name = TOOL_DISPLAY_NAMES.get(tool_name, tool_name)

        # 发送 tool_call 事件
        append_tool_call_event(
            session_id=session_id,
            tool_name=tool_name,
            tool_display_name=display_name,
            description=f"执行 {display_name}",
            estimated_time=3.0
        )

        # 执行工具
        try:
            context = {
                **tool_args,
                "session_id": session_id,
                "project_name": state.get("project_name", "")
            }
            result = ToolRegistry.execute_tool(tool_name, context)

            append_tool_result_event(
                session_id=session_id,
                tool_name=tool_name,
                status="success",
                summary=f"{display_name} 执行成功",
                data_preview=result[:200] if isinstance(result, str) else str(result)[:200]
            )

            tool_results.append({
                "tool_call_id": tool_call.get("id", ""),
                "role": "tool",
                "content": result
            })

            # 更新 active_tools
            active_tools = list(state.get("active_tools", []))
            active_tools.append({
                "name": tool_name,
                "status": "success",
                "result_preview": result[:100] if isinstance(result, str) else str(result)[:100]
            })

        except Exception as e:
            error_msg = str(e)
            logger.error(f"[tool_execution] {tool_name} 失败: {error_msg}")

            append_tool_result_event(
                session_id=session_id,
                tool_name=tool_name,
                status="error",
                summary=f"{display_name} 执行失败",
                data_preview=error_msg
            )

            tool_results.append({
                "tool_call_id": tool_call.get("id", ""),
                "role": "tool",
                "content": f"错误: {error_msg}"
            })

    # 转换为 ToolMessage 格式
    from langchain_core.messages import ToolMessage
    result_messages = [
        ToolMessage(
            content=r["content"],
            tool_call_id=r["tool_call_id"]
        )
        for r in tool_results
    ]

    return {
        "messages": result_messages,
        "active_tools": state.get("active_tools", [])
    }


def planning_step_node(state: ConversationState) -> Dict[str, Any]:
    """
    规划步骤节点 - 执行下一阶段规划

    根据当前阶段调用相应的规划子图。
    """
    phase = state.get("current_phase", PlanningPhase.INIT.value)
    context = state.get("planning_context", {})
    session_id = state["session_id"]
    project_name = state.get("project_name", "")

    # 阶段映射
    phase_handlers = {
        PlanningPhase.INIT.value: _handle_init_phase,
        PlanningPhase.LAYER1_ANALYSIS.value: _handle_layer1_phase,
        PlanningPhase.LAYER2_CONCEPT.value: _handle_layer2_phase,
        PlanningPhase.LAYER3_DETAIL.value: _handle_layer3_phase,
    }

    handler = phase_handlers.get(phase, _handle_init_phase)
    result = handler(state, session_id, project_name, context)

    return result


def answer_question_node(state: ConversationState) -> Dict[str, Any]:
    """
    问答节点 - 回答用户问题

    基于规划上下文和已有成果，回答用户问题。
    """
    messages = state["messages"]
    reports = state.get("reports", {})
    context = state.get("planning_context", {})

    # 构建上下文感知的系统提示
    system_prompt = f"""你是一个村庄规划助手。请根据已有信息回答用户问题。

当前规划进度：{state.get('current_phase', '初始化')}

已有规划成果：
{_format_reports_for_context(reports)}

规划任务：{context.get('task_description', '未指定')}
约束条件：{context.get('constraints', '无')}

请用简洁、专业的语言回答问题。如果问题与当前规划无关，请友好地引导用户回归规划主题。"""

    llm = create_llm(model=LLM_MODEL, temperature=0.5, max_tokens=MAX_TOKENS)

    # 只取最近几轮对话
    recent_messages = list(messages)[-6:]
    full_messages = [SystemMessage(content=system_prompt)] + recent_messages

    response = llm.invoke(full_messages)

    return {"messages": [response]}


# ==========================================
# 意图路由
# ==========================================

def intent_router(state: ConversationState) -> str:
    """
    意图路由 - 根据用户意图决定下一步

    Returns:
        路由目标节点名称
    """
    messages = state["messages"]

    # 获取最后一条用户消息
    last_user_message = None
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            last_user_message = msg
            break

    if not last_user_message:
        return "conversation"

    # 使用 LLM 分类意图
    intent = classify_intent(
        user_message=last_user_message.content,
        state=state
    )

    logger.info(f"[intent_router] 分类意图: {intent.value}")

    # 路由映射
    route_map = {
        UserIntent.CONTINUE_PLANNING: "planning_step",
        UserIntent.RUN_TOOL: "tool_execution",
        UserIntent.ASK_QUESTION: "answer_question",
        UserIntent.REQUEST_DETAILS: "answer_question",
        UserIntent.REQUEST_REVISION: "planning_step",
        UserIntent.APPROVE: "planning_step",
        UserIntent.REJECT: "conversation",
        UserIntent.START_PLANNING: "planning_step",
        UserIntent.ROLLBACK: "planning_step",
        UserIntent.UNKNOWN: "conversation",  # fallback
    }

    return route_map.get(intent, "conversation")


# ==========================================
# 图构建
# ==========================================

def create_conversation_graph(checkpointer=None) -> StateGraph:
    """
    创建对话式规划图

    Args:
        checkpointer: LangGraph 检查点存储器

    Returns:
        编译后的 StateGraph
    """
    builder = StateGraph(ConversationState)

    # 添加节点
    builder.add_node("conversation", conversation_node)
    builder.add_node("tool_execution", tool_execution_node)
    builder.add_node("planning_step", planning_step_node)
    builder.add_node("answer_question", answer_question_node)

    # 定义边
    builder.add_edge(START, "conversation")

    # 条件路由
    builder.add_conditional_edges(
        "conversation",
        intent_router,
        {
            "tool_execution": "tool_execution",
            "planning_step": "planning_step",
            "answer_question": "answer_question",
            "conversation": "conversation",  # 继续对话
            "end": END
        }
    )

    # 工具执行后返回对话
    builder.add_edge("tool_execution", "conversation")

    # 规划步骤后返回对话
    builder.add_edge("planning_step", "conversation")

    # 问答后返回对话
    builder.add_edge("answer_question", "conversation")

    # 编译图
    return builder.compile(checkpointer=checkpointer)


# ==========================================
# 辅助函数
# ==========================================

def _build_system_prompt(state: ConversationState) -> str:
    """构建系统提示"""
    phase = state.get("current_phase", PlanningPhase.INIT.value)
    project_name = state.get("project_name", "村庄")
    context = state.get("planning_context", {})

    phase_descriptions = {
        PlanningPhase.INIT.value: "初始化阶段，准备开始规划",
        PlanningPhase.LAYER1_ANALYSIS.value: "现状分析阶段，正在分析村庄现状",
        PlanningPhase.LAYER1_REVIEW.value: "现状分析审核，等待用户确认",
        PlanningPhase.LAYER2_CONCEPT.value: "规划思路阶段，正在制定规划方向",
        PlanningPhase.LAYER2_REVIEW.value: "规划思路审核，等待用户确认",
        PlanningPhase.LAYER3_DETAIL.value: "详细规划阶段，正在制定具体方案",
        PlanningPhase.LAYER3_REVIEW.value: "详细规划审核，等待用户确认",
        PlanningPhase.COMPLETED.value: "规划已完成",
    }

    return f"""你是村庄规划助手，正在进行 {project_name} 的规划工作。

当前阶段：{phase_descriptions.get(phase, '未知')}

规划任务：{context.get('task_description', '制定村庄发展规划')}
约束条件：{context.get('constraints', '无特殊约束')}

你可以：
1. 回答用户关于规划的问题
2. 调用工具获取数据（GIS分析、POI搜索等）
3. 推进规划进度
4. 根据用户反馈调整规划

请根据用户意图自然地响应。"""


def _format_reports_for_context(reports: Dict[str, Dict[str, str]]) -> str:
    """格式化报告用于上下文"""
    if not reports:
        return "暂无已完成的规划成果"

    lines = []
    for layer, dims in reports.items():
        layer_names = {"layer1": "现状分析", "layer2": "规划思路", "layer3": "详细规划"}
        lines.append(f"\n{layer_names.get(layer, layer)}:")
        for dim, content in dims.items():
            preview = content[:100] + "..." if len(content) > 100 else content
            lines.append(f"  - {dim}: {preview}")

    return "\n".join(lines)


async def _handle_init_phase(state: ConversationState, session_id: str, project_name: str, context: PlanningContext) -> Dict[str, Any]:
    """处理初始化阶段"""
    return {
        "current_phase": PlanningPhase.LAYER1_ANALYSIS.value,
        "messages": [AIMessage(content=f"开始 {project_name} 的现状分析...")]
    }


async def _handle_layer1_phase(state: ConversationState, session_id: str, project_name: str, context: PlanningContext) -> Dict[str, Any]:
    """处理 Layer 1 现状分析"""
    from ..subgraphs.analysis_subgraph import call_analysis_subgraph

    result = await call_analysis_subgraph(
        raw_data=context.get("village_data", ""),
        project_name=project_name,
        session_id=session_id
    )

    if result.get("success"):
        reports = dict(state.get("reports", {}))
        reports["layer1"] = result.get("analysis_reports", {})

        return {
            "reports": reports,
            "current_phase": PlanningPhase.LAYER1_REVIEW.value,
            "completed_dimensions": {"layer1": list(result.get("analysis_reports", {}).keys())},
            "messages": [AIMessage(content=f"现状分析完成，分析了 {len(result.get('analysis_reports', {}))} 个维度。请查看结果并确认是否继续。")],
            "pending_review": True
        }
    else:
        return {
            "messages": [AIMessage(content="现状分析遇到问题，请稍后重试。")]
        }


async def _handle_layer2_phase(state: ConversationState, session_id: str, project_name: str, context: PlanningContext) -> Dict[str, Any]:
    """处理 Layer 2 规划思路"""
    from ..subgraphs.concept_subgraph import call_concept_subgraph

    reports = state.get("reports", {})
    analysis_reports = reports.get("layer1", {})

    result = await call_concept_subgraph(
        analysis_reports=analysis_reports,
        project_name=project_name,
        session_id=session_id
    )

    if result.get("success"):
        reports["layer2"] = result.get("concept_reports", {})

        return {
            "reports": reports,
            "current_phase": PlanningPhase.LAYER2_REVIEW.value,
            "completed_dimensions": {**state.get("completed_dimensions", {}), "layer2": list(result.get("concept_reports", {}).keys())},
            "messages": [AIMessage(content=f"规划思路已生成。请查看并确认。")],
            "pending_review": True
        }
    else:
        return {
            "messages": [AIMessage(content="规划思路生成遇到问题，请稍后重试。")]
        }


async def _handle_layer3_phase(state: ConversationState, session_id: str, project_name: str, context: PlanningContext) -> Dict[str, Any]:
    """处理 Layer 3 详细规划"""
    from ..subgraphs.detailed_plan_subgraph import call_detailed_plan_subgraph

    reports = state.get("reports", {})
    concept_reports = reports.get("layer2", {})

    result = await call_detailed_plan_subgraph(
        concept_reports=concept_reports,
        project_name=project_name,
        session_id=session_id
    )

    if result.get("success"):
        reports["layer3"] = result.get("detail_reports", {})

        return {
            "reports": reports,
            "current_phase": PlanningPhase.COMPLETED.value,
            "completed_dimensions": {**state.get("completed_dimensions", {}), "layer3": list(result.get("detail_reports", {}).keys())},
            "messages": [AIMessage(content=f"详细规划已完成！所有规划成果已生成。")],
            "pending_review": False
        }
    else:
        return {
            "messages": [AIMessage(content="详细规划生成遇到问题，请稍后重试。")]
        }


__all__ = [
    "ConversationState",
    "PlanningPhase",
    "create_conversation_graph",
    "conversation_node",
    "tool_execution_node",
    "planning_step_node",
    "intent_router",
]