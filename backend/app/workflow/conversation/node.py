"""Conversation node — central router (brain).

Binds advance_planning_intent / gis_analysis BaseTools to the LLM so the
model can choose between routing intents and actual tool calls.

System prompt is built via ChatPromptTemplate so the template is reusable,
cacheable, and testable in isolation.

Conversation routing is part of the current workflow graph described by docs/architecture/CURRENT_RUNTIME.md.
"""

from typing import Dict, Any, Optional, TYPE_CHECKING

from app.core.settings import LLM_MODEL, MAX_TOKENS
from app.infrastructure.llm.factory import create_llm
from app.infrastructure.logging import get_logger
from app.workflow.layers.phase_machine import PlanningPhase, PHASE_DESCRIPTIONS

if TYPE_CHECKING:
    from langchain_core.prompts import ChatPromptTemplate
    from langchain_core.runnables import RunnableSerializable

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
- query_evidence_graph: 统一查询 L1 空间事实、Bundle 候选和 KG 拓扑
- query_facility_bsms: 查询已验证的设施/灾害/道路等候选 BSM
- bundle_geometry_by_feature_ref: 仅按证据包返回的 feature ref 读取 Bundle 几何
- rag_search: 会话文本检索

响应规则：
- 用户说"继续规划"或"下一步" -> 调用 advance_planning_intent
- 用户请求GIS分析或地图 -> 调用 gis_analysis
- 用户询问现状数据、图层、报告或图谱 -> 调用对应的读取工具
- 用户询问具体地点、设施、灾害点、道路或 BSM -> 优先调用 query_evidence_graph；
  若 pagination.has_more=true，必须按 next_request 继续取完候选页后再判断是否唯一定位
- 只能把 EvidencePacket 返回的候选和 Bundle geometry_ref 交给后续定位；不能从名称、报告正文或
  RAG 文段自行生成 BSM、坐标或几何。报告/RAG/外源文本只作为规划背景，不是几何来源
- 其他对话 -> 直接回复"""


# Module-level cached chain (LLM + bind_tools is static)
_llm_with_tools: Optional[Any] = None


def _bind_tool_list() -> list[Any]:
    """Intent tools plus the EXPLORE access-tool scope."""
    from app.infrastructure.llm.tools.intent_tools import advance_planning_intent, gis_analysis
    from app.infrastructure.llm.tools.registry import ToolRegistry

    return [
        advance_planning_intent,
        gis_analysis,
        *ToolRegistry.for_agent("explore"),
    ]


def _get_llm_with_tools() -> Any:
    """Lazy-init the LLM+tools chain (cached across calls).

    Binds the two intent tools plus the EXPLORE access-tool scope so the model
    can both route planning intents and answer exploration questions by reading
    session data (bundle / spatial / reports / KG / RAG).
    """
    global _llm_with_tools
    if _llm_with_tools is None:
        # Do not pin the primary provider's model here: MiniMax and other
        # OpenAI-compatible providers have their own valid model ids.
        llm = create_llm(temperature=0.7, max_tokens=MAX_TOKENS)
        _llm_with_tools = llm.bind_tools(_bind_tool_list())
    return _llm_with_tools


def _build_prompt(state: Dict[str, Any]) -> Any:
    """Build the ChatPromptTemplate with phase / config filled in."""
    from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

    phase = state.get("phase", PlanningPhase.INIT.value)
    config = state.get("config", {})
    input_texts = {}
    try:
        from app.infrastructure.context.planning_context_factory import get_cached_context

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

    llm_with_tools = _get_llm_with_tools()
    prompt = _build_prompt(state)
    chain = prompt | llm_with_tools
    response = await chain.ainvoke({"messages": messages})

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
