"""LangChain @tool definitions for execute_tools_node.

The legacy analytics tools (population_prediction / knowledge_search /
web_search) were removed — their backing ``analytics`` package was deleted.
The module keeps an empty tool surface so downstream consumers
(execute_tools_node / DataPipeline / conversation node) can keep resolving
``TOOL_REGISTRY`` and ``get_tools_for_llm()`` safely.
"""

from typing import Dict, List

ALL_TOOLS: List = []
TOOL_REGISTRY: Dict[str, object] = {}


def get_tools_for_llm():
    return ALL_TOOLS


__all__ = [
    "ALL_TOOLS",
    "TOOL_REGISTRY",
    "get_tools_for_llm",
]
