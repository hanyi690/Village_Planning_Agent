"""allocate_zones tool — MIP optimization for planning zone allocation."""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Annotated

from langchain_core.tools import tool, InjectedToolCallId
from langgraph.prebuilt import InjectedState
from langgraph.types import Command

from app.utils.logger import get_logger
from ._helpers import make_result, to_tool_message

logger = get_logger(__name__)


@tool
def allocate_zones(
    targets: Annotated[Optional[Dict[str, Any]], InjectedState("intent")],
    kg_constraints: Annotated[Optional[List[Dict[str, Any]]], InjectedState("kg_constraints")],
    gis_data: Annotated[Dict[str, Optional[Dict[str, Any]]], InjectedState("gis_data")],
    tool_call_id: Annotated[str, InjectedToolCallId] = "",
    mode: str = "mip",
) -> Command:
    """Allocate planning zones using MIP optimization.

    Uses hard constraints from KG (construction cap, farmland floor, ecological).
    Land use data auto-injected from state.
    """
    t0 = time.time()

    landuse_geojson = gis_data.get("landuse_current_geojson") if gis_data else None
    if not landuse_geojson or not landuse_geojson.get("features"):
        return Command(update={
            "messages": [to_tool_message(
                make_result(False, error="No land use data available"), tool_call_id
            )],
        })

    try:
        from app.services.modules.gis.optimizer.mip_allocator import MIPZoneAllocator

        allocator = MIPZoneAllocator()
        allocated_geojson, alloc_trace = allocator.solve(
            landuse_geojson=landuse_geojson,
            targets=targets if targets else {},
            constraints=kg_constraints,
        )

        summary = {
            "mode": alloc_trace.get("mode", mode),
            "allocated_count": len(allocated_geojson.get("features", [])),
            "elapsed_s": round(time.time() - t0, 2),
        }

        return Command(update={
            "allocated_geojson": allocated_geojson,
            "allocation_summary": summary,
            "messages": [to_tool_message(make_result(True, data=summary), tool_call_id)],
        })

    except Exception as e:
        logger.error(f"Allocation failed: {e}")
        return Command(update={
            "messages": [to_tool_message(make_result(False, error=str(e)), tool_call_id)],
        })
