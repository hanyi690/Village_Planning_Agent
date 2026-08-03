"""LangChain tool adapters for the GIS knowledge-graph service."""

from __future__ import annotations

from typing import Annotated, Any, Dict, Optional

from langchain_core.tools import InjectedToolCallId, tool
from langgraph.prebuilt import InjectedState
from langgraph.types import Command

from app.modules.kg.service import build_knowledge_graph_data
from app.tools.helpers import make_result, to_tool_message


@tool
def build_knowledge_graph(
    reports: Annotated[Dict[str, Dict[str, Any]], InjectedState("reports")],
    gis_data: Annotated[
        Dict[str, Optional[Dict[str, Any]]],
        InjectedState("gis_data"),
    ],
    village_name: Annotated[str, InjectedState("village_name")],
    session_id: Annotated[str, InjectedState("session_id")],
    intent: Annotated[Optional[Dict[str, Any]], InjectedState("intent")] = None,
    tool_call_id: Annotated[str, InjectedToolCallId] = "",
) -> Command:
    """LangChain wrapper around the direct KG build service."""
    update = build_knowledge_graph_data(
        reports=reports,
        gis_data=gis_data,
        village_name=village_name,
        session_id=session_id,
        intent=intent,
    )
    metrics = update.pop("kg_build_metrics", {})
    update["messages"] = [
        to_tool_message(make_result(True, data=metrics), tool_call_id)
    ]
    return Command(update=update)


@tool
def query_knowledge_graph(
    template_name: str,
    session_id: Annotated[str, InjectedState("session_id")],
    tool_call_id: Annotated[str, InjectedToolCallId] = "",
    **params: Any,
) -> Command:
    """Query the session graph with a registered SPARQL template."""
    from app.modules.kg.manager import get_kg_manager

    manager = get_kg_manager()
    kg = manager.get_session_kg(session_id)
    if kg is None:
        return Command(update={
            "messages": [
                to_tool_message(
                    make_result(
                        False,
                        error="KG not built — call build_knowledge_graph first",
                    ),
                    tool_call_id,
                )
            ],
        })

    query_result = manager.query_with_cache(
        session_id,
        kg,
        template_name,
        **params,
    )
    result = make_result(True, data={
        "template": template_name,
        "params": params,
        "results": query_result,
    })
    return Command(update={
        "messages": [to_tool_message(result, tool_call_id)],
    })


__all__ = [
    "build_knowledge_graph",
    "query_knowledge_graph",
]
