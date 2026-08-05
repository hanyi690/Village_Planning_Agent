"""LangChain tool adapter for the GIS output-package service."""

from __future__ import annotations

from typing import Annotated, Any, Dict, List, Optional

from langchain_core.tools import InjectedToolCallId, tool
from langgraph.prebuilt import InjectedState
from langgraph.types import Command

from app.modules.spatial_ops.output.export_package import export_gdb_package
from app.tools.helpers import make_result, to_tool_message


@tool
def export_gdb(
    layout_configs: Annotated[
        Optional[List[Dict[str, Any]]],
        InjectedState("layout_configs"),
    ],
    allocated_geojson: Annotated[
        Optional[Dict[str, Any]],
        InjectedState("allocated_geojson"),
    ],
    gis_data: Annotated[
        Dict[str, Optional[Dict[str, Any]]],
        InjectedState("gis_data"),
    ],
    village_name: Annotated[str, InjectedState("village_name")],
    session_id: Annotated[str, InjectedState("session_id")] = "",
    tool_call_id: Annotated[str, InjectedToolCallId] = "",
    output_dir: Optional[str] = None,
) -> Command:
    """Export the complete package matching the GIS layer registry."""
    data = export_gdb_package(
        layout_configs=layout_configs,
        allocated_geojson=allocated_geojson,
        gis_data=gis_data,
        village_name=village_name,
        output_dir=output_dir,
        session_id=session_id,
    )
    result = make_result(True, data=data)
    return Command(update={
        "messages": [to_tool_message(result, tool_call_id)],
    })


__all__ = ["export_gdb"]
