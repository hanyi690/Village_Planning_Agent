"""
村庄规划主图 - Router Agent 架构

单一图、单一 State，实现：
1. conversation_node 作为中央路由（大脑）
2. intent_router 决定下一步
3. Send API 并行执行维度
4. 完整的时光倒流（Checkpoint 记录聊天+规划）

架构流程：
    [用户输入]
        │
        ▼
    conversation_node (LLM: bind_tools)
        │ intent_router
        ├─► [闲聊/问答] END
        ├─► [工具调用] execute_tools
        └─► [推进规划] route_by_phase
                              │
                       [Send N 维度]
                              │
                              ▼
                      analyze_dimension
                              │
                       emit_sse_events
                              │
                              ▼
                      collect_results
                              │
                              ▼
                      check_completion
                              │
                   ┌──────────┴──────────┐
                   ▼                      ▼
             advance_phase           conversation
                   │                      │
                   └──────────────────────┘
"""

import asyncio
from typing import TypedDict, List, Dict, Any, Literal, Optional, Union
from typing_extensions import Annotated
from langgraph.graph import StateGraph, END, START
from langgraph.graph.message import add_messages
from langgraph.types import Send
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage, ToolMessage

from ..core.config import LLM_MODEL, MAX_TOKENS
from ..core.llm_factory import create_llm
from ..utils.logger import get_logger
from ..utils.sse_publisher import SSEPublisher
from ..tools.registry import ToolRegistry

# 编排层组件
from .state import (
    UnifiedPlanningState,
    PlanningPhase,
    PlanningConfig,
    create_initial_state,
    get_layer_dimensions,
    get_wave_dimensions,
    get_total_waves,
    get_next_phase,
    _phase_to_layer,
    _layer_to_phase,
    LAYER_NAMES,
    PHASE_DESCRIPTIONS,
)
from .routing import (
    intent_router,
    route_by_phase,
    collect_layer_results,
    emit_sse_events,
    check_phase_completion,
)
from .nodes.dimension_node import (
    analyze_dimension_for_send,
    create_dimension_state,
    knowledge_preload_node,
    DIMENSION_NAMES,
    get_layer_from_dimension,
)
from .nodes.revision_node import revision_node

logger = get_logger(__name__)


# ==========================================
# Graph Caching (avoid repeated construction)
# ==========================================

_cached_graph = None
_graph_checkpointer_ref = None


# ==========================================
# 工具定义（从共享常量导入）
# ==========================================

from src.constants.tools import ADVANCE_PLANNING_TOOL


# ==========================================
# 对话节点（中央路由 - 大脑）
# ==========================================

async def conversation_node(state: UnifiedPlanningState) -> Dict[str, Any]:
    """
    中央路由节点（大脑）

    使用 LLM bind_tools 实现意图识别：
    - 普通对话：直接回复
    - 工具调用：返回 tool_calls
    - 推进规划：返回 AdvancePlanningIntent
    """
    messages = list(state.get("messages", []))
    phase = state.get("phase", PlanningPhase.INIT.value)
    project_name = state.get("project_name", "")
    config = state.get("config", {})
    reports = state.get("reports", {})
    previous_layer = state.get("previous_layer", 0)

    # 构建系统提示（传递恢复执行信息）
    system_prompt = _build_system_prompt(
        phase, project_name, config, reports,
        previous_layer=previous_layer
    )

    # 获取 LLM 并绑定工具
    llm = create_llm(model=LLM_MODEL, temperature=0.7, max_tokens=MAX_TOKENS)
    llm_with_tools = llm.bind_tools([ADVANCE_PLANNING_TOOL])

    # 构建消息
    full_messages = [SystemMessage(content=system_prompt)] + messages

    # 调用 LLM
    response = await llm_with_tools.ainvoke(full_messages)

    logger.info(f"[对话节点] LLM 响应: tool_calls={getattr(response, 'tool_calls', None)}")

    return {"messages": [response]}


def _build_system_prompt(
    phase: str,
    project_name: str,
    config: PlanningConfig,
    reports: Dict[str, Dict[str, str]],
    previous_layer: int = 0
) -> str:
    """构建系统提示"""
    # 格式化已有报告
    reports_summary = ""
    for layer_key, layer_reports in reports.items():
        if layer_reports:
            layer_name = LAYER_NAMES.get(layer_key, layer_key)
            reports_summary += f"\n{layer_name}:\n"
            for dim_key, content in list(layer_reports.items())[:3]:
                dim_name = DIMENSION_NAMES.get(dim_key, dim_key)
                preview = content[:100] + "..." if len(content) > 100 else content
                reports_summary += f"  - {dim_name}: {preview}\n"

    # 恢复执行提示（当 phase 是 layer2/3 且 previous_layer 为 0 时表示刚恢复）
    resume_hint = ""
    layer_num = 0
    if phase.startswith("layer"):
        try:
            layer_num = int(phase.replace("layer", ""))
        except ValueError:
            pass

    # 检测恢复执行状态：phase 已推进到下一层，previous_layer=0 表示刚批准
    if layer_num in [2, 3] and previous_layer == 0:
        completed_layer = layer_num - 1
        resume_hint = f"""

【恢复执行提示】
用户已批准 Layer {completed_layer} 的审查结果，现在需要继续执行 Layer {layer_num} 的规划分析。
请立即调用 AdvancePlanningIntent 工具开始下一层的规划分析，无需等待用户再次确认。"""

    return f"""你是村庄规划助手，正在进行 {project_name} 的规划工作。

当前阶段：{PHASE_DESCRIPTIONS.get(phase, '未知')}
{resume_hint}

规划任务：{config.get('task_description', '制定村庄发展规划')}
约束条件：{config.get('constraints', '无特殊约束')}
{f"已有成果：{reports_summary}" if reports_summary else ""}

你可以：
1. 回答用户关于规划的问题
2. 调用工具获取数据（使用标准工具调用格式）
3. 推进规划进度（调用 AdvancePlanningIntent 工具）

请根据用户意图自然地响应。如果用户表示要"继续规划"、"开始分析"、"下一步"等，请调用 AdvancePlanningIntent 工具。"""


# ==========================================
# 工具执行节点
# ==========================================

async def execute_tools_node(state: UnifiedPlanningState) -> Dict[str, Any]:
    """
    工具执行节点

    执行 LLM 返回的工具调用，发送完整的工具事件流：
    tool_call -> tool_progress -> tool_result
    """
    messages = state.get("messages", [])
    session_id = state.get("session_id", "")

    last_message = messages[-1] if messages else None
    if not last_message or not hasattr(last_message, "tool_calls"):
        return {"messages": []}

    tool_calls = getattr(last_message, "tool_calls", [])
    if not tool_calls:
        return {"messages": []}

    # 过滤掉 AdvancePlanningIntent（已由 intent_router 处理）
    regular_tool_calls = [tc for tc in tool_calls if tc.get("name") != "AdvancePlanningIntent"]

    if not regular_tool_calls:
        return {"messages": []}

    tool_results = []

    for tool_call in regular_tool_calls:
        tool_name = tool_call.get("name", "")
        tool_args = tool_call.get("args", {})

        logger.info(f"[工具执行] 执行工具: {tool_name}")

        # 单次查找获取所有工具元数据
        tool_info = ToolRegistry.get_tool_info(tool_name)

        # 发送 tool_call 事件
        SSEPublisher.send_tool_call(
            session_id=session_id,
            tool_name=tool_name,
            tool_display_name=tool_info["display_name"],
            description=tool_info["description"],
            estimated_time=tool_info["estimated_time"]
        )

        try:
            # 使用工厂方法创建进度回调
            progress_callback = SSEPublisher.create_progress_callback(
                session_id=session_id,
                tool_name=tool_name
            )

            context = {
                **tool_args,
                "session_id": session_id,
                "project_name": state.get("project_name", ""),
                "progress_callback": progress_callback
            }
            result = ToolRegistry.execute_tool(tool_name, context)

            tool_results.append(
                ToolMessage(
                    content=str(result),
                    tool_call_id=tool_call.get("id", "")
                )
            )

            # 发送 tool_result 成功事件
            SSEPublisher.send_tool_result(
                session_id=session_id,
                tool_name=tool_name,
                status="success",
                result_preview=str(result)[:200]
            )

        except Exception as e:
            error_msg = f"工具执行失败: {str(e)}"
            logger.error(f"[工具执行] {tool_name} 失败: {e}")

            tool_results.append(
                ToolMessage(
                    content=error_msg,
                    tool_call_id=tool_call.get("id", "")
                )
            )

            # 发送 tool_result 错误事件
            SSEPublisher.send_tool_result(
                session_id=session_id,
                tool_name=tool_name,
                status="error",
                error=str(e)
            )

    return {"messages": tool_results}


# ==========================================
# 维度分析节点（Send API 目标）
# ==========================================

async def analyze_dimension(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    维度分析节点（Send API 目标）

    调用 analyze_dimension_for_send 返回 dimension_results 和 sse_events。
    """
    return await analyze_dimension_for_send(state)


# ==========================================
# 收集和推进节点
# ==========================================

def collect_results(state: UnifiedPlanningState) -> Dict[str, Any]:
    """收集维度分析结果"""
    return collect_layer_results(state)


def emit_events(state: UnifiedPlanningState) -> Dict[str, Any]:
    """发送 SSE 事件"""
    return emit_sse_events(state)


def check_completion(state: UnifiedPlanningState) -> Literal["continue", "advance", "complete", "revision", "pause"]:
    """检查阶段完成状态"""
    if state.get("need_revision"):
        return "revision"

    result = check_phase_completion(state)

    if result == "complete":
        return "complete"
    elif result == "advance":
        return "advance"
    elif result == "pause":
        return "pause"
    else:
        return "continue"


def advance_phase(state: UnifiedPlanningState) -> Dict[str, Any]:
    """推进到下一阶段"""
    phase = state.get("phase", PlanningPhase.INIT.value)
    next_phase = get_next_phase(phase)

    if next_phase:
        logger.info(f"[阶段推进] {phase} -> {next_phase}")
        return {
            "phase": next_phase,
            "current_wave": 1
        }

    return {}


# ==========================================
# 路由函数
# ==========================================

def route_intent(state: UnifiedPlanningState) -> Literal["execute_tools", "route_planning", "end"]:
    """意图路由"""
    return intent_router(state)


def route_planning(state: UnifiedPlanningState) -> Union[List[Send], str]:
    """规划路由（Send API）"""
    return route_by_phase(state)


# ==========================================
# 构建主图
# ==========================================

def create_unified_planning_graph(checkpointer=None) -> StateGraph:
    """
    创建统一规划图（Router Agent 架构）

    单一 State，消灭双写问题。
    Checkpoint 完整记录聊天+规划。

    Uses caching to avoid repeated graph construction.
    """
    global _cached_graph, _graph_checkpointer_ref

    # Cache hit: return cached graph
    if _cached_graph is not None and _graph_checkpointer_ref is checkpointer:
        logger.debug("[图构建] 使用缓存的 Router Agent 图")
        return _cached_graph

    # Cache miss: build new graph
    logger.info("[图构建] 开始构建 Router Agent 图")

    builder = StateGraph(UnifiedPlanningState)

    # 添加节点
    builder.add_node("conversation", conversation_node)
    builder.add_node("execute_tools", execute_tools_node)
    builder.add_node("knowledge_preload", knowledge_preload_node)
    builder.add_node("analyze_dimension", analyze_dimension)
    builder.add_node("emit_events", emit_events)
    builder.add_node("collect_results", collect_results)
    builder.add_node("advance_phase", advance_phase)
    builder.add_node("revision", revision_node)

    # 路由节点（空操作，仅用于触发条件路由）
    def route_planning_node(state: UnifiedPlanningState) -> Dict[str, Any]:
        """
        规划路由节点 - 为 AdvancePlanningIntent 添加 ToolMessage 响应

        解决 OpenAI API 报错：tool_call 后必须有 ToolMessage
        """
        messages = state.get("messages", [])
        last_msg = messages[-1] if messages else None

        if last_msg and hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
            for tool_call in last_msg.tool_calls:
                if tool_call.get("name") == "AdvancePlanningIntent":
                    logger.info("[规划路由] 为 AdvancePlanningIntent 添加 ToolMessage")
                    return {
                        "messages": [
                            ToolMessage(
                                content="规划流程已启动，开始分析维度...",
                                tool_call_id=tool_call.get("id", "")
                            )
                        ]
                    }
        return {}
    builder.add_node("route_planning", route_planning_node)

    # 入口：对话节点
    builder.add_edge(START, "conversation")

    # 意图路由
    builder.add_conditional_edges(
        "conversation",
        route_intent,
        {
            "execute_tools": "execute_tools",
            "route_planning": "route_planning",
            END: END
        }
    )

    # 工具执行后返回对话
    builder.add_edge("execute_tools", "conversation")

    # 规划路由（Send API 动态分发）
    builder.add_conditional_edges(
        "route_planning",
        route_planning,
        {
            "knowledge_preload": "knowledge_preload",
            "analyze_dimension": "analyze_dimension",
            "revision": "revision",
            "collect_results": "collect_results",
            "advance_phase": "advance_phase",
            END: END
        }
    )

    # 知识预加载完成后，返回路由重新分发
    builder.add_edge("knowledge_preload", "route_planning")

    # 维度分析 -> 发送事件
    builder.add_edge("analyze_dimension", "emit_events")

    # 发送事件 -> 收集结果
    builder.add_edge("emit_events", "collect_results")

    # 收集结果 -> 检查完成
    builder.add_conditional_edges(
        "collect_results",
        check_completion,
        {
            "continue": "conversation",  # 继续当前阶段
            "advance": "advance_phase",  # 推进到下一阶段
            "complete": END,             # 规划完成
            "revision": "revision",      # 进入修订
            "pause": END                 # 暂停等待审查
        }
    )

    # 阶段推进 -> 路由分发
    builder.add_edge("advance_phase", "route_planning")

    # 修订 -> 返回对话
    builder.add_edge("revision", "conversation")

    # 编译图
    graph = builder.compile(checkpointer=checkpointer)
    logger.info("[图构建] Router Agent 图构建完成")

    # Update cache
    _cached_graph = graph
    _graph_checkpointer_ref = checkpointer

    return graph


# ==========================================
# 对外接口
# ==========================================

def run_unified_planning(
    session_id: str,
    project_name: str,
    village_data: str,
    task_description: str = "制定村庄总体规划方案",
    constraints: str = "无特殊约束",
    checkpointer=None
) -> Dict[str, Any]:
    """
    执行统一规划流程

    Args:
        session_id: 会话 ID
        project_name: 项目名称
        village_data: 村庄数据
        task_description: 任务描述
        constraints: 约束条件
        checkpointer: LangGraph checkpointer

    Returns:
        最终状态
    """
    logger.info(f"[统一规划] 开始执行: {project_name}")

    graph = create_unified_planning_graph(checkpointer)

    initial_state = create_initial_state(
        session_id=session_id,
        project_name=project_name,
        village_data=village_data,
        task_description=task_description,
        constraints=constraints
    )

    result = graph.invoke(initial_state)

    logger.info(f"[统一规划] 执行完成")
    return result


async def run_unified_planning_async(
    session_id: str,
    project_name: str,
    village_data: str,
    task_description: str = "制定村庄总体规划方案",
    constraints: str = "无特殊约束",
    checkpointer=None,
    config: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    异步执行统一规划流程

    Args:
        session_id: 会话 ID
        project_name: 项目名称
        village_data: 村庄数据
        task_description: 任务描述
        constraints: 约束条件
        checkpointer: LangGraph checkpointer
        config: 图配置（如 thread_id）

    Returns:
        最终状态
    """
    logger.info(f"[统一规划-异步] 开始执行: {project_name}")

    graph = create_unified_planning_graph(checkpointer)

    initial_state = create_initial_state(
        session_id=session_id,
        project_name=project_name,
        village_data=village_data,
        task_description=task_description,
        constraints=constraints
    )

    invoke_config = {}
    if config:
        invoke_config["configurable"] = config

    result = await graph.ainvoke(initial_state, config=invoke_config)

    logger.info(f"[统一规划-异步] 执行完成")
    return result


def resume_from_checkpoint(
    checkpoint_id: str,
    session_id: str,
    checkpointer=None
) -> Dict[str, Any]:
    """从检查点恢复执行"""
    logger.info(f"[统一规划] 从检查点恢复: {checkpoint_id}")

    graph = create_unified_planning_graph(checkpointer)
    config = {"configurable": {"thread_id": session_id, "checkpoint_id": checkpoint_id}}
    result = graph.invoke(None, config)

    return result


__all__ = [
    "UnifiedPlanningState",
    "PlanningPhase",
    "create_unified_planning_graph",
    "run_unified_planning",
    "run_unified_planning_async",
    "resume_from_checkpoint",
]