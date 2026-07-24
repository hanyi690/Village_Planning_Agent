"""allocate_zones tool — MIP optimization for planning zone allocation."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Annotated

from langchain_core.tools import tool, InjectedToolCallId
from langgraph.prebuilt import InjectedState
from langgraph.types import Command

from app.utils.logger import get_logger
from app.tools.helpers import make_result, to_tool_message

logger = get_logger(__name__)


# ── PARSE constraint → MIP constraint conversion ──────────────────


def _spatial_constraint_to_mip(constraint: Any) -> Optional[Dict[str, Any]]:
    """Convert SpatialConstraint (PARSE output) to MIP-compatible constraint dict.

    MIP allocator expects dicts with: constraint_id, field, operator, value, source.

    Mapping:
      - area_constraint + land_use → area field constraint
      - 省标 6 大类 (ecological_protection/farmland_protection/etc.) → KG field constraint
      - spatial_constraint (no_overlap/buffer_exclusion) → geometry filter, not MIP
      - building_constraint → field constraint if value present
    """
    # Typed SpatialConstraint path
    if hasattr(constraint, 'type') and hasattr(constraint, 'model_dump'):
        ctype = constraint.type
        value = getattr(constraint, 'value', None)

        # 省标 6 大类 → field mapping
        provincial_map = {
            "ecological_protection": ("ecological_area_ha", ">="),
            "farmland_protection": ("farmland_area_ha", ">="),
            "construction_control": ("construction_area_ha", "<="),
            "heritage_protection": ("heritage_protection_ha", ">="),
            "safety_assurance": ("safety_zone_ha", ">="),
            "other_control": (None, None),
        }

        if ctype in provincial_map:
            field, operator = provincial_map[ctype]
            if field and value is not None:
                return {
                    "constraint_id": f"parse_{ctype}",
                    "field": field,
                    "operator": operator,
                    "value": float(value),
                    "source": "parse_provincial",
                }
            return None

        # area_constraint → land_use based field
        if ctype == "area_constraint" and value is not None:
            land_use = getattr(constraint, 'land_use', '') or ''
            area_field_map = {
                "construction": "construction_area_ha",
                "farmland": "farmland_area_ha",
                "ecological": "ecological_area_ha",
            }
            field = area_field_map.get(land_use.lower())
            if field:
                operator = getattr(constraint, 'operator', '>=') or '>='
                return {
                    "constraint_id": f"parse_area_{land_use}",
                    "field": field,
                    "operator": operator,
                    "value": float(value),
                    "source": "parse_area",
                }

        # building_constraint → max area/height/floors
        if ctype == "building_constraint" and value is not None:
            max_area = getattr(constraint, 'max_area_sqm', None)
            max_height = getattr(constraint, 'max_height_m', None)
            max_floors = getattr(constraint, 'max_floors', None)
            if max_area:
                return {
                    "constraint_id": "parse_building_area",
                    "field": "building_max_area_sqm",
                    "operator": "<=",
                    "value": float(max_area),
                    "source": "parse_building",
                }
            if max_height:
                return {
                    "constraint_id": "parse_building_height",
                    "field": "building_max_height_m",
                    "operator": "<=",
                    "value": float(max_height),
                    "source": "parse_building",
                }

        # spatial_constraint type → geometry filter (not MIP)
        return None

    # Legacy dict path
    if isinstance(constraint, dict):
        ctype = constraint.get("type", "")
        value = constraint.get("value")
        if ctype == "area_constraint" and value is not None:
            land_use = constraint.get("land_use", "").lower()
            area_field_map = {
                "construction": "construction_area_ha",
                "farmland": "farmland_area_ha",
                "ecological": "ecological_area_ha",
            }
            field = area_field_map.get(land_use)
            if field:
                return {
                    "constraint_id": f"parse_area_{land_use}",
                    "field": field,
                    "operator": constraint.get("operator", ">="),
                    "value": float(value),
                    "source": "parse_area",
                }

    return None


@dataclass
class AllocationIntent:
    """Enriched intent from PARSE — all zone_target fields consumed (Step 4)."""
    target_map: Dict[str, float] = field(default_factory=dict)   # zone_type → area_ha
    density_hints: Dict[str, str] = field(default_factory=dict)   # zone_type → "high"/"medium"/"low"
    adjacency_rules: Dict[str, dict] = field(default_factory=dict)  # zone_type → {prefer, avoid}
    vne_codes: Dict[str, str] = field(default_factory=dict)       # zone_type → VNE code


def _intent_to_targets(intent: Any, total_area_ha: float) -> AllocationIntent:
    """Convert typed SpatialPlanningIntent to AllocationIntent (Step 4).

    Phase 4: replaces _build_legacy_intent bridge. ZoneTarget.area_ratio (0-1)
    is converted to absolute area_ha using total parcel area.
    Step 4: also extracts density_hints, adjacency_rules, vne_codes.
    """
    result = AllocationIntent()
    if intent is None:
        return result

    # Typed path: SpatialPlanningIntent.zone_targets (List[ZoneTarget])
    if hasattr(intent, 'zone_targets') and intent.zone_targets:
        for zt in intent.zone_targets:
            if hasattr(zt, 'land_use') and hasattr(zt, 'area_ratio'):
                area_ha = zt.area_ratio * total_area_ha if total_area_ha > 0 else zt.area_ratio
                result.target_map[zt.land_use] = round(area_ha, 2)

                # Step 4: density hints
                if hasattr(zt, 'density') and zt.density:
                    result.density_hints[zt.land_use] = zt.density

                # Step 4: adjacency rules
                if hasattr(zt, 'adjacency_rules') and zt.adjacency_rules:
                    ar = zt.adjacency_rules
                    result.adjacency_rules[zt.land_use] = {
                        "prefer": ar.prefer if hasattr(ar, 'prefer') else [],
                        "avoid": ar.avoid if hasattr(ar, 'avoid') else [],
                    }

                # Step 4: VNE codes
                if hasattr(zt, 'vne_code') and zt.vne_code:
                    result.vne_codes[zt.land_use] = zt.vne_code

        return result

    # Legacy dict fallback (old code — should be unreachable after migration)
    if isinstance(intent, dict):
        for z in intent.get("zones", []):
            lu = z.get("land_use", z.get("zone_id", "?"))
            result.target_map[lu] = z.get("area_ratio", 0) * total_area_ha
    return result


@tool
def allocate_zones(
    targets: Annotated[Any, InjectedState("intent")],
    kg_constraints: Annotated[Optional[List[Dict[str, Any]]], InjectedState("kg_constraints")],
    gis_data: Annotated[Dict[str, Optional[Dict[str, Any]]], InjectedState("gis_data")],
    kg_adjacency_map: Annotated[Optional[Dict[str, Any]], InjectedState("kg_adjacency_map")] = None,
    constraint_set: Annotated[Optional[List[Dict[str, Any]]], InjectedState("constraint_set")] = None,
    constraint_adjustments: Annotated[Optional[List[Dict[str, Any]]], InjectedState("constraint_adjustments")] = None,
    facility_anchors: Annotated[Optional[List[Dict[str, Any]]], InjectedState("facility_anchors")] = None,
    kg_protected_parcels_detail: Annotated[Optional[List[Dict[str, Any]]], InjectedState("kg_protected_parcels_detail")] = None,
    tool_call_id: Annotated[str, InjectedToolCallId] = "",
    mode: str = "mip",
) -> Command:
    """Allocate planning zones using MIP optimization.

    Uses hard constraints from KG (construction cap, farmland floor, ecological).
    Phase 3: adjacency map from KG available for spatially-coherent allocation.
    Step 1: PARSE constraint_set injected as MIP constraints.
    Step 3: constraint_adjustments from validate fed back to correct targets.
    Phase 5: kg_protected_parcels_detail for spatial containment exclusion.
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

    # Phase 3: Log adjacency map availability for spatially-coherent allocation
    adj_count = len(kg_adjacency_map) if kg_adjacency_map else 0
    if adj_count:
        logger.info("[allocate] KG adjacency map available: %d parcels", adj_count)

    # Convert typed SpatialPlanningIntent -> AllocationIntent (Step 4)
    alloc_intent = _intent_to_targets(targets, total_area_ha)
    target_map = alloc_intent.target_map

    # Step 3: Apply constraint_adjustments from validate feedback loop
    if constraint_adjustments:
        for adj in constraint_adjustments:
            zone = adj.get("zone", "")
            delta = adj.get("delta_ha", 0)
            if zone in target_map and delta:
                target_map[zone] = round(target_map[zone] + delta, 2)
                logger.info("[allocate] Adjusted %s by %+.1f ha (reason: %s)",
                            zone, delta, adj.get("reason", ""))

    # Step 4: Convert PARSE constraint_set to MIP-compatible constraints
    mip_parse_constraints = []
    if constraint_set:
        for c in constraint_set:
            mip_c = _spatial_constraint_to_mip(c)
            if mip_c:
                mip_parse_constraints.append(mip_c)
        if mip_parse_constraints:
            logger.info("[allocate] %d PARSE constraints converted to MIP", len(mip_parse_constraints))

    logger.info(
        "[allocate] Intent converted: %d zones, %.1f ha total, %d PARSE constraints → %s",
        len(target_map), total_area_ha, len(mip_parse_constraints),
        " | ".join(f"{k}={v:.1f}ha" for k, v in target_map.items()),
    )

    # Step 4: Log enriched intent fields
    if alloc_intent.density_hints:
        logger.info("[allocate] Density hints: %s", alloc_intent.density_hints)
    if alloc_intent.adjacency_rules:
        logger.info("[allocate] Adjacency rules: %d zones with rules", len(alloc_intent.adjacency_rules))
    if alloc_intent.vne_codes:
        logger.info("[allocate] VNE codes: %s", alloc_intent.vne_codes)

    # Merge all constraints: KG constraints + PARSE area constraints
    all_constraints = list(kg_constraints or [])
    if mip_parse_constraints:
        all_constraints.extend(mip_parse_constraints)
        logger.info("[allocate] %d PARSE area constraints merged with %d KG constraints",
                    len(mip_parse_constraints), len(all_constraints) - len(mip_parse_constraints))

    try:
        from ._generation.optimizer.mip_allocator import MIPZoneAllocator

        allocator = MIPZoneAllocator()
        allocated_geojson, alloc_trace = allocator.solve(
            landuse_geojson=landuse_geojson,
            targets=target_map,
            constraints=all_constraints,
            parse_constraints=constraint_set,  # Raw SpatialConstraint list for DLBM-based exclusion
            density_hints=alloc_intent.density_hints or None,
            adjacency_rules=alloc_intent.adjacency_rules or None,
            facility_anchors=facility_anchors,
            protected_parcels_detail=kg_protected_parcels_detail,  # Phase 5: spatial containment exclusion
        )

        summary = {
            "mode": alloc_trace.get("mode", mode),
            "allocated_count": len(allocated_geojson.get("features", [])),
            "elapsed_s": round(time.time() - t0, 2),
        }

        # Step 4: Record enriched intent fields in summary
        if alloc_intent.density_hints:
            summary["density_hints"] = alloc_intent.density_hints
        if alloc_intent.adjacency_rules:
            summary["adjacency_rules"] = alloc_intent.adjacency_rules
        if alloc_intent.vne_codes:
            summary["vne_codes"] = alloc_intent.vne_codes

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
