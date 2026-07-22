"""allocate_zones tool — MIP optimization for planning zone allocation."""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Annotated

from langchain_core.tools import tool, InjectedToolCallId
from langgraph.prebuilt import InjectedState
from langgraph.types import Command

from app.utils.logger import get_logger
from app.tools.helpers import make_result, to_tool_message

logger = get_logger(__name__)


def _intent_to_targets(intent: Any, total_area_ha: float) -> Dict[str, float]:
    """Convert typed SpatialPlanningIntent to {zone_type: target_area_ha} dict.

    Phase 4: replaces _build_legacy_intent bridge. ZoneTarget.area_ratio (0-1)
    is converted to absolute area_ha using total parcel area.
    """
    targets: Dict[str, float] = {}
    if intent is None:
        return targets
    # Typed path: SpatialPlanningIntent.zone_targets (List[ZoneTarget])
    if hasattr(intent, 'zone_targets') and hasattr(intent, 'zone_targets')[0:]:
        for zt in intent.zone_targets:
            if hasattr(zt, 'land_use') and hasattr(zt, 'area_ratio'):
                area_ha = zt.area_ratio * total_area_ha if total_area_ha > 0 else zt.area_ratio
                targets[zt.land_use] = round(area_ha, 2)
        return targets
    # Legacy dict fallback (old code — should be unreachable after migration)
    if isinstance(intent, dict):
        for z in intent.get("zones", []):
            targets[z.get("land_use", z.get("zone_id", "?"))] = z.get("area_ratio", 0) * total_area_ha
    return targets


@tool
def allocate_zones(
    targets: Annotated[Any, InjectedState("intent")],
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

    # Compute total area from GeoJSON for area_ratio -> absolute conversion
    total_area_ha = 0.0
    for feat in landuse_geojson.get("features", []):
        props = feat.get("properties", {})
        total_area_ha += float(props.get("area_ha", props.get("面积", 0)) or 0)

    # Convert typed SpatialPlanningIntent -> {zone_type: target_area}
    target_map = _intent_to_targets(targets, total_area_ha)
    logger.info(
        "[allocate] Intent converted: %d zones, %.1f ha total → %s",
        len(target_map), total_area_ha,
        " | ".join(f"{k}={v:.1f}ha" for k, v in target_map.items()),
    )

    try:
        from app.modules.gis.generation.optimizer.mip_allocator import MIPZoneAllocator

        allocator = MIPZoneAllocator()
        allocated_geojson, alloc_trace = allocator.solve(
            landuse_geojson=landuse_geojson,
            targets=target_map,
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
