"""Conversation node — central router (brain).

Binds advance_planning_intent / gis_analysis BaseTools plus the analytics
tools (population_prediction, knowledge_search, web_search) to the LLM so
the model can choose between routing intents and actual tool calls.

System prompt is built via ChatPromptTemplate so the template is reusable,
cacheable, and testable in isolation.
"""

from typing import Dict, Any, Optional

from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.runnables import RunnableSerializable

from app.core.settings import LLM_MODEL, MAX_TOKENS
from ...core.llm import create_llm
from app.utils.logger import get_logger
from ..state import PlanningPhase, PHASE_DESCRIPTIONS
from app.tools.intent_tools import advance_planning_intent, gis_analysis
from app.tools.tools import get_tools_for_llm

logger = get_logger(__name__)


SYSTEM_TEMPLATE = """你是村庄规划助手，正在进行 {project_name} 的规划工作。

当前阶段：{phase_desc}
规划任务：{task_desc}
约束条件：{constraints}

可用工具：
- AdvancePlanningIntent: 推进规划流程
- GISAnalysis: GIS可视化分析
- population_prediction: 人口预测
- knowledge_search: 知识检索
- web_search: 网络搜索

响应规则：
- 用户说"继续规划"或"下一步" -> 调用 AdvancePlanningIntent
- 用户请求GIS分析或地图 -> 调用 GISAnalysis
- 其他对话 -> 直接回复"""


# Module-level cached chain (LLM + bind_tools is static)
_llm_with_tools: Optional[RunnableSerializable] = None


def _get_llm_with_tools() -> RunnableSerializable:
    """Lazy-init the LLM+tools chain (cached across calls)."""
    global _llm_with_tools
    if _llm_with_tools is None:
        llm = create_llm(model=LLM_MODEL, temperature=0.7, max_tokens=MAX_TOKENS)
        bind_list = [advance_planning_intent, gis_analysis] + list(get_tools_for_llm())
        _llm_with_tools = llm.bind_tools(bind_list)
    return _llm_with_tools


def _build_prompt(state: Dict[str, Any]) -> ChatPromptTemplate:
    """Build the ChatPromptTemplate with phase / config filled in."""
    phase = state.get("phase", PlanningPhase.INIT.value)
    config = state.get("config", {})
    return ChatPromptTemplate.from_messages([
        ("system", SYSTEM_TEMPLATE),
        MessagesPlaceholder("messages"),
    ]).partial(
        project_name=state.get("project_name", ""),
        phase_desc=PHASE_DESCRIPTIONS.get(phase, "未知"),
        task_desc=config.get("task_description", "制定村庄发展规划"),
        constraints=config.get("constraints", "无特殊约束"),
    )


async def conversation_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Central routing node — parse user intent and decide next step.

    Returns:
        messages: list with a single AIMessage (may have tool_calls)
    """
    messages = list(state.get("messages", []))

    llm_with_tools = _get_llm_with_tools()
    prompt = _build_prompt(state)
    chain = prompt | llm_with_tools
    response = await chain.ainvoke({"messages": messages})

    logger.info(f"[对话] tool_calls={getattr(response, 'tool_calls', None)}")
    return {"messages": [response]}


__all__ = ["conversation_node", "SYSTEM_TEMPLATE"]
