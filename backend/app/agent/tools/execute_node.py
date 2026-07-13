"""Tool execution node — dispatches tool calls via LangChain BaseTool.ainvoke.

Filters out intent tools (advance_planning_intent / gis_analysis) routed
elsewhere, then invokes the remaining BaseTools in parallel. SSE events
are published around each invocation.
"""

import asyncio
import json
from typing import Dict, Any, Tuple
from langchain_core.messages import ToolMessage

from app.utils.logger import get_logger
from ...utils.sse_publisher import SSEPublisher
from ...tools.registry import ToolRegistry
from ...tools.tools import TOOL_REGISTRY
from app.tools.intent_tools import advance_planning_intent, gis_analysis

logger = get_logger(__name__)

_ROUTING_NAMES = frozenset({advance_planning_intent.name, gis_analysis.name})

# LLM may emit PascalCase names from old prompts; map them to snake_case
_NAME_ALIASES = {
    "AdvancePlanningIntent": advance_planning_intent.name,
    "GISAnalysis": gis_analysis.name,
}


def _normalize_name(name: str) -> str:
    """Normalize tool name: resolve PascalCase aliases to registered snake_case."""
    return _NAME_ALIASES.get(name, name)


async def _invoke_single(
    tc: Dict[str, Any],
    session_id: str,
    state: Dict[str, Any],
) -> ToolMessage:
    """Invoke a single tool call with SSE publishing."""
    tool_name = _normalize_name(tc.get("name", ""))
    tool_args = tc.get("args", {}) or {}
    tool_id = tc.get("id", "")

    try:
        tool_info = ToolRegistry.get_tool_info(tool_name)
        SSEPublisher.send_tool_started(
            session_id, tool_name,
            tool_info["display_name"],
            tool_info["description"],
            tool_info["estimated_time"]
        )

        base_tool = TOOL_REGISTRY.get(tool_name)
        if base_tool is None:
            raise ValueError(f"工具未注册: {tool_name}")

        result = await base_tool.ainvoke({**tool_args, "state": state})

        logger.info(
            "[execute_tools] %s completed: result_len=%d tool_id=%s",
            tool_name, len(str(result)) if result else 0, tool_id,
        )

        SSEPublisher.send_tool_status(
            session_id, tool_name, status="success",
            summary=str(result)[:200]
        )
        return ToolMessage(content=str(result), tool_call_id=tool_id)

    except Exception as e:
        SSEPublisher.send_tool_status(
            session_id, tool_name, status="error", error=str(e)
        )
        logger.error("[工具执行] %s 失败: %s", tool_name, e)
        return ToolMessage(content=f"工具执行失败: {e}", tool_call_id=tool_id)


async def execute_tools_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Execute non-routing tool calls from the last AIMessage in parallel."""
    messages = state.get("messages", [])
    session_id = state.get("session_id", "")

    last_msg = messages[-1] if messages else None
    if not last_msg or not hasattr(last_msg, "tool_calls"):
        return {"messages": []}

    regular_calls = [
        tc for tc in getattr(last_msg, "tool_calls", [])
        if _normalize_name(tc.get("name")) not in _ROUTING_NAMES
    ]
    if not regular_calls:
        return {"messages": []}

    tool_summary = [
        f"{_normalize_name(tc.get('name', ' unknown '))}({json.dumps(tc.get('args', {}), ensure_ascii=False)[:200]})"
        for tc in regular_calls
    ]
    logger.info(
        "[execute_tools] session=%s tools=%d: %s",
        session_id, len(regular_calls), "; ".join(tool_summary),
    )

    results = await asyncio.gather(*[
        _invoke_single(tc, session_id, state) for tc in regular_calls
    ])
    return {"messages": list(results)}


__all__ = ["execute_tools_node"]
