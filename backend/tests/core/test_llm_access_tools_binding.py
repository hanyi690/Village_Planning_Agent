"""P3: LLM access tools become executable via the unified ToolRegistry."""

from __future__ import annotations

from app.infrastructure.llm.tools.registry import ToolRegistry
from app.workflow.conversation.node import _bind_tool_list


def test_access_tools_are_registered_as_executable() -> None:
    import app.infrastructure.llm.tools.access  # noqa: F401  (triggers _register())

    for name in (
        "bundle_overview",
        "spatial_context",
        "spatial_features",
        "layer_reports",
        "knowledge_graph",
        "rag_search",
    ):
        assert ToolRegistry.get_tool(name) is not None, name
        info = ToolRegistry.get_tool_info(name)
        assert info["display_name"]


def test_bind_tool_list_contains_intent_and_explore_access_tools() -> None:
    tools = _bind_tool_list()
    names = [getattr(tool, "name", "") for tool in tools]

    assert "advance_planning_intent" in names
    assert "gis_analysis" in names
    assert {"bundle_overview", "spatial_context", "spatial_features"} <= set(names)


def test_execute_node_resolves_registered_tool_not_legacy_registry() -> None:
    import app.workflow.tools.execute_node as execute_node

    assert execute_node.ToolRegistry is ToolRegistry
    assert not hasattr(execute_node, "TOOL_REGISTRY")
