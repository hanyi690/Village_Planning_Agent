"""
工具执行节点 - 执行 GIS 和其他工具

处理 LLM 的 tool_calls，执行并返回结果。
"""

from typing import Dict, Any
from langchain_core.messages import ToolMessage

from app.utils.logger import get_logger
from ...utils.sse_publisher import SSEPublisher
from ...tools.registry import ToolRegistry
from app.tools.constants import ADVANCE_PLANNING_TOOL

logger = get_logger(__name__)


async def execute_tools_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    工具执行节点 - 处理非推进类的工具调用

    Returns:
        messages: 包含 ToolMessage 结果
    """
    messages = state.get("messages", [])
    session_id = state.get("session_id", "")

    last_msg = messages[-1] if messages else None
    if not last_msg or not hasattr(last_msg, "tool_calls"):
        return {"messages": []}

    tool_calls = getattr(last_msg, "tool_calls", [])
    # 过滤掉 AdvancePlanningIntent（由路由处理）
    regular_calls = [tc for tc in tool_calls
                     if tc.get("name") != ADVANCE_PLANNING_TOOL["function"]["name"]]

    if not regular_calls:
        return {"messages": []}

    tool_results = []
    for tc in regular_calls:
        tool_name = tc.get("name", "")
        tool_args = tc.get("args", {})
        tool_id = tc.get("id", "")

        try:
            tool_info = ToolRegistry.get_tool_info(tool_name)
            SSEPublisher.send_tool_call(
                session_id, tool_name,
                tool_info["display_name"],
                tool_info["description"],
                tool_info["estimated_time"]
            )

            result = ToolRegistry.execute_tool(tool_name, {
                **tool_args,
                "session_id": session_id,
                "project_name": state.get("project_name", "")
            })

            tool_results.append(ToolMessage(
                content=str(result),
                tool_call_id=tool_id
            ))
            SSEPublisher.send_tool_result(
                session_id, tool_name,
                status="success",
                result_preview=str(result)[:200]
            )
        except Exception as e:
            tool_results.append(ToolMessage(
                content=f"工具执行失败: {e}",
                tool_call_id=tool_id
            ))
            SSEPublisher.send_tool_result(
                session_id, tool_name,
                status="error",
                error=str(e)
            )
            logger.error(f"[工具执行] {tool_name} 失败: {e}")

    return {"messages": tool_results}


__all__ = ["execute_tools_node"]