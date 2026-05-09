"""
对话节点 - 中央路由（大脑）

处理用户对话，绑定推进规划和GIS工具。
"""

from typing import Dict, Any
from langchain_core.messages import SystemMessage

from app.core.settings import LLM_MODEL, MAX_TOKENS
from ...core.llm import create_llm
from app.utils.logger import get_logger
from ..state import PlanningPhase, PHASE_DESCRIPTIONS
from app.tools.constants import ADVANCE_PLANNING_TOOL, GIS_ANALYSIS_TOOL

logger = get_logger(__name__)


async def conversation_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    中央路由节点 - 解析用户意图并决定下一步

    Returns:
        messages: 包含 LLM 响应（可能有 tool_calls）
    """
    messages = list(state.get("messages", []))
    phase = state.get("phase", PlanningPhase.INIT.value)
    project_name = state.get("project_name", "")
    config = state.get("config", {})

    system_prompt = f"""你是村庄规划助手，正在进行 {project_name} 的规划工作。

当前阶段：{PHASE_DESCRIPTIONS.get(phase, '未知')}
规划任务：{config.get('task_description', '制定村庄发展规划')}
约束条件：{config.get('constraints', '无特殊约束')}

可用工具：
- AdvancePlanningIntent: 推进规划流程
- GISAnalysis: GIS可视化分析

响应规则：
- 用户说"继续规划"或"下一步" -> 调用 AdvancePlanningIntent
- 用户请求GIS分析或地图 -> 调用 GISAnalysis
- 其他对话 -> 直接回复"""

    llm = create_llm(model=LLM_MODEL, temperature=0.7, max_tokens=MAX_TOKENS)
    llm_with_tools = llm.bind_tools([ADVANCE_PLANNING_TOOL, GIS_ANALYSIS_TOOL])

    full_messages = [SystemMessage(content=system_prompt)] + messages
    response = await llm_with_tools.ainvoke(full_messages)

    logger.info(f"[对话] tool_calls={getattr(response, 'tool_calls', None)}")
    return {"messages": [response]}


__all__ = ["conversation_node"]