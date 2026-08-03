"""render_map tool — convert GeoJSON layers to frontend MapLibre format.

Merges:
  - layout/map_renderer.py (MapRenderer)
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Annotated

from langchain_core.tools import tool, InjectedToolCallId
from langchain_core.messages import ToolMessage
from langgraph.prebuilt import InjectedState
from langgraph.types import Command

from app.utils.logger import get_logger

logger = get_logger(__name__)

from app.utils.sse_events import GISLayerConfig


from app.tools.helpers import make_result, to_tool_message


def build_map_layers(
    layout_configs: Optional[List[Dict[str, Any]]],
    gis_data: Dict[str, Optional[Dict[str, Any]]],
) -> List[Dict[str, Any]]:
    """Build frontend MapLibre layers without LangChain tool wrapping."""
    layers: List[Dict[str, Any]] = []

    for cfg in layout_configs or []:
        if isinstance(cfg, dict) and cfg.get("data"):
            layers.append({
                "geojson": cfg["data"],
                "layer_type": cfg.get("layerType", "function_zone"),
                "layer_name": cfg.get("layer_name") or cfg.get("layerType", "layer"),
                "color": cfg.get("color"),
                "style": cfg.get("style"),
            })

    if gis_data.get("boundary_geojson"):
        layers.append({
            "geojson": gis_data["boundary_geojson"],
            "layer_type": "boundary",
            "layer_name": "boundary",
            "color": "#3388ff",
        })

    if gis_data.get("landuse_current_geojson"):
        layers.append({
            "geojson": gis_data["landuse_current_geojson"],
            "layer_type": "function_zone",
            "layer_name": "current_landuse",
            "color": None,
        })

    return [GISLayerConfig(**layer).model_dump(by_alias=True) for layer in layers]


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
