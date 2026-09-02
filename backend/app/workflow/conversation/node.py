"""Conversation node — central router (brain).

Binds advance_planning_intent / gis_analysis BaseTools to the LLM so the
model can choose between routing intents and actual tool calls.

System prompt is built via ChatPromptTemplate so the template is reusable,
cacheable, and testable in isolation.

Conversation routing is part of the current workflow graph described by docs/architecture/CURRENT_RUNTIME.md.
"""

from typing import Dict, Any

from app.infrastructure.logging import get_logger
from app.workflow.layers.phase_machine import PlanningPhase, PHASE_DESCRIPTIONS

logger = get_logger(__name__)


SYSTEM_TEMPLATE = """你是村庄规划助手，正在进行 {project_name} 的规划工作。

当前阶段：{phase_desc}
规划任务：{task_desc}
约束条件：{constraints}

可用工具：
- advance_planning_intent: 推进规划流程
- gis_analysis: GIS可视化分析
- bundle_overview: 会话数据概览
- spatial_context: 空间语义认知
- spatial_features: 空间要素清单
- layer_reports: 维度报告
- knowledge_graph: 知识图谱查询
- data_geometry_by_ref: 仅按 EvidencePacket 返回的 DATA ref 读取几何
- rag_search: 会话文本检索

响应规则：
- 用户说"继续规划"或"下一步" -> 调用 advance_planning_intent
- 用户请求GIS分析或地图 -> 调用 gis_analysis
- 用户询问现状数据、图层、报告或图谱 -> 调用对应的读取工具
- 用户询问具体地点、设施、灾害点或道路 -> 先由 Evidence 按 requirement/query plan
  取得候选；需要查看几何时只调用 data_geometry_by_ref
- 只能把 EvidencePacket 返回的候选和 DATA geometry_ref 交给后续定位；不能从名称、报告正文或
  RAG 文段自行生成身份、坐标或几何。报告/RAG/外源文本只作为规划背景，不是几何来源
- 其他对话 -> 直接回复"""


def _bind_tool_list() -> list[Any]:
    """Intent tools plus the EXPLORE access-tool scope."""
    from app.infrastructure.llm.tools.intent_tools import advance_planning_intent, gis_analysis
    from app.infrastructure.llm.tools.registry import ToolRegistry

    return [
        advance_planning_intent,
        gis_analysis,
        *ToolRegistry.for_agent("explore"),
    ]


def _build_prompt(state: Dict[str, Any]) -> Any:
    """Build the ChatPromptTemplate with phase / config filled in."""
    from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

    phase = state.get("phase", PlanningPhase.INIT.value)
    config = state.get("config", {})
    input_texts = {}
    try:
        from app.infrastructure.context_runtime.manager import get_cached_context

        context = get_cached_context(str(state.get("session_id", "")))
        input_texts = context.input_texts() if context is not None else {}
    except Exception:
        input_texts = {}
    return ChatPromptTemplate.from_messages([
        ("system", SYSTEM_TEMPLATE),
        MessagesPlaceholder("messages"),
    ]).partial(
        project_name=state.get("project_name", ""),
        phase_desc=PHASE_DESCRIPTIONS.get(phase, "未知"),
        task_desc=input_texts.get("task_description", "制定村庄发展规划"),
        constraints=input_texts.get("constraints", "无特殊约束"),
    )


async def conversation_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Central routing node — parse user intent and decide next step.

    Returns:
        messages: list with a single AIMessage (may have tool_calls)
    """
    messages = list(state.get("messages", []))

    # If the last message already carries a known intent tool_call
    # (injected by trigger_planning_execution), skip the LLM and route directly.
    last_msg = messages[-1] if messages else None
    if last_msg and hasattr(last_msg, 'tool_calls') and last_msg.tool_calls:
        known = {"advance_planning_intent", "gis_analysis", "GISAnalysis"}
        for tc in last_msg.tool_calls:
            if tc.get("name") in known:
                logger.info(
                    "[conversation] Existing intent '%s' detected, bypassing LLM",
                    tc.get("name"),
                )
                return {}

    prompt = _build_prompt(state)
    prompt_value = prompt.invoke({"messages": messages})
    from app.infrastructure.llm.manager import get_llm_manager

    response = await get_llm_manager().run_tool_calling(
        stage="conversation",
        contract_key="conversation.tool_routing",
        messages=list(prompt_value.messages),
        tools=_bind_tool_list(),
        context={
            "session_id": state.get("session_id", ""),
            "phase": state.get("phase", ""),
        },
    )

    tool_calls = getattr(response, 'tool_calls', None)
    has_content = bool(getattr(response, 'content', None))
    logger.info(
        "[conversation] tool_calls=%s content=%s phase=%s",
        tool_calls, has_content, state.get("phase"),
    )
    if not tool_calls and not has_content:
        logger.warning("[conversation] LLM returned no tool_calls and no content — possible prompt issue")
    return {"messages": [response]}


__all__ = ["conversation_node", "SYSTEM_TEMPLATE"]
