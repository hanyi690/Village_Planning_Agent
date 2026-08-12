"""Shared helpers for all tool modules.

Provides make_result() and to_tool_message() as the standard
tool-return protocol across the entire tools layer.
"""

import json
from typing import Any, Dict

from langchain_core.messages import ToolMessage


def make_result(success: bool, data: Any = None, error: str = "") -> Dict[str, Any]:
    payload: Dict[str, Any] = {"success": success}
    if data is not None:
        payload["data"] = data
    if error:
        payload["error"] = error
    return payload


def to_tool_message(result: Dict[str, Any], tool_call_id: str) -> ToolMessage:
    return ToolMessage(
        content=json.dumps(result, ensure_ascii=False, default=str),
        tool_call_id=tool_call_id,
    )
