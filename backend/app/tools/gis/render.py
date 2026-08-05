"""render_map tool — convert GeoJSON layers to frontend MapLibre format.

Renders layers directly from spatial data via spatial_ops.map_layers.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Annotated

from langchain_core.tools import tool, InjectedToolCallId
from langchain_core.messages import ToolMessage
from langgraph.prebuilt import InjectedState
from langgraph.types import Command

from app.utils.logger import get_logger
from app.modules.spatial_ops.output.map_layers import build_map_layers

logger = get_logger(__name__)

from app.tools.helpers import make_result, to_tool_message


@tool
def render_map(
    layout_configs: Annotated[Optional[List[Dict[str, Any]]], InjectedState("layout_configs")],
    gis_data: Annotated[Dict[str, Optional[Dict[str, Any]]], InjectedState("gis_data")],
    tool_call_id: Annotated[str, InjectedToolCallId] = "",
) -> Command:
    """Render layout layers to GISLayerConfig format for frontend MapLibre display.

    Converts internal GeoJSON layers to the frontend GISLayerConfig spec
    with proper layer_type, colors, and styling. Data auto-injected from state.
    """
    layers = build_map_layers(layout_configs, gis_data)

    result = make_result(True, data={
        "layers": layers,
        "layer_count": len(layers),
    })

    return Command(update={
        "messages": [to_tool_message(result, tool_call_id)],
    })
