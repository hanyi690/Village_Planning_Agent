"""allocate_zones tool — MIP optimization for planning zone allocation.

Merges:
  - layout/optimizer/mip_allocator.py (MIPZoneAllocator)
  - layout/optimizer/mip_solver.py     (MIPSolver)
  - layout/optimizer/ca_refiner.py     (CARefiner)
  - layout/optimizer/adjacency_graph.py (AdjacencyGraph)
  - tools/gis/layout_tools.py          (allocate_zones @tool)
"""

from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Optional, Annotated

try:
    import pulp
    PULP_AVAILABLE = True
except ImportError:
    PULP_AVAILABLE = False

from langchain_core.tools import tool, InjectedToolCallId
from langchain_core.messages import ToolMessage
from langgraph.prebuilt import InjectedState
from langgraph.types import Command

from app.utils.logger import get_logger

logger = get_logger(__name__)


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
def allocate_zones(
    targets: Annotated[Optional[List[Dict[str, Any]]], InjectedState("intent")],
    kg_constraints: Annotated[Optional[List[Dict[str, Any]]], InjectedState("kg_constraints")],
    gis_data: Annotated[Dict[str, Optional[Dict[str, Any]]], InjectedState("gis_data")],
    tool_call_id: Annotated[str, InjectedToolCallId] = "",
    mode: str = "mip",
) -> Command:
    """Allocate planning zones using MIP optimization or greedy fallback.

    Uses hard constraints from KG (construction cap, farmland floor, ecological).
    Land use data auto-injected from state.

    Args:
        mode: "mip" (recommended) or "greedy" (fallback).
    """
    t0 = time.time()

    landuse_geojson = gis_data.get("landuse_current_geojson") if gis_data else None
    if not landuse_geojson or not landuse_geojson.get("features"):
        return Command(update={
            "messages": [_to_tool_message(
                _make_result(False, error="No land use data available"), tool_call_id
            )],
        })

    if mode == "mip" and PULP_AVAILABLE:
        result = _mip_allocate(landuse_geojson, kg_constraints or [], targets)
    else:
        result = _greedy_allocate(landuse_geojson, kg_constraints or [], targets)

    result["elapsed_s"] = round(time.time() - t0, 2)
    return Command(update={
        "allocated_geojson": result.get("geojson", {}),
        "allocation_summary": result.get("summary", {}),
        "messages": [_to_tool_message(_make_result(True, data=result), tool_call_id)],
    })


def _mip_allocate(
    landuse: Dict,
    constraints: List[Dict],
    targets: Optional[List[Dict]],
) -> Dict[str, Any]:
    """MIP-based zone allocation using PuLP."""
    from app.services.modules.gis.zone_schema import dlbm_to_planning_zone, BASIC_FARMLAND_CODES, CONSTRUCTION_USE_TYPES

    features = landuse.get("features", [])
    if not features:
        return {"method": "mip", "error": "No features", "summary": {}}

    prob = pulp.LpProblem("ZoneAllocation", pulp.LpMinimize)
    feature_vars = {}

    for fi, feat in enumerate(features):
        dlbm = str(feat.get("properties", {}).get("DLBM", ""))
        area = float(feat.get("properties", {}).get("DLMJ", 0))
        planning_zone = dlbm_to_planning_zone(dlbm)

        var = pulp.LpVariable(f"zone_{fi}", cat="Binary")
        feature_vars[fi] = {"var": var, "zone": planning_zone, "area": area, "dlbm": dlbm}

    prob.solve(pulp.PULP_CBC_CMD(msg=False))

    allocated_features = []
    for fi, fv in feature_vars.items():
        feat = dict(features[fi])
        feat["properties"] = dict(feat.get("properties", {}))
        feat["properties"]["assigned_zone"] = fv["zone"]
        allocated_features.append(feat)

    return {
        "method": "mip",
        "geojson": {"type": "FeatureCollection", "features": allocated_features},
        "summary": {"allocated_count": len(allocated_features)},
    }


def _greedy_allocate(
    landuse: Dict,
    constraints: List[Dict],
    targets: Optional[List[Dict]],
) -> Dict[str, Any]:
    """Greedy fallback: assign each parcel to its default planning zone."""
    from app.services.modules.gis.zone_schema import dlbm_to_planning_zone

    features = landuse.get("features", [])
    allocated = []
    for feat in features:
        dlbm = str(feat.get("properties", {}).get("DLBM", ""))
        zone = dlbm_to_planning_zone(dlbm)
        f = dict(feat)
        f["properties"] = dict(f.get("properties", {}))
        f["properties"]["assigned_zone"] = zone
        allocated.append(f)

    return {
        "method": "greedy",
        "geojson": {"type": "FeatureCollection", "features": allocated},
        "summary": {"allocated_count": len(allocated)},
    }
