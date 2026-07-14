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

from app.services.modules.gis.schema import GISLayerConfig


def _make_result(success: bool, data: Any = None, error: str = "") -> Dict[str, Any]:
    payload: Dict[str, Any] = {"success": success}
    if data is not None:
        payload["data"] = data
    if error:
        payload["error"] = error
    return payload


def _to_tool_message(result: Dict[str, Any], tool_call_id: str) -> ToolMessage:
    return ToolMessage(
        content=json.dumps(result, ensure_ascii=False, default=str),
        tool_call_id=tool_call_id,
    )


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
    layers: List[Dict[str, Any]] = []

    # Parse layout configs into GISLayerConfig format
    if layout_configs:
        for cfg in layout_configs:
            if isinstance(cfg, dict) and cfg.get("data"):
                layers.append({
                    "geojson": cfg["data"],
                    "layer_type": cfg.get("layerType", "function_zone"),
                    "layer_name": cfg.get("layerType", "layer"),
                    "color": cfg.get("color"),
                    "style": cfg.get("style"),
                })

    # Add base layers from GIS data
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

    result = _make_result(True, data={
        "layers": [GISLayerConfig(**l).model_dump(by_alias=True) for l in layers],
        "layer_count": len(layers),
    })

    return Command(update={
        "messages": [_to_tool_message(result, tool_call_id)],
    })
