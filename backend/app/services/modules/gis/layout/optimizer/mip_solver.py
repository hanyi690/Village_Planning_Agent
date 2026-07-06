"""
Constraint-driven zone allocator.

Replaces DLBM reclassification with a constraint-aware greedy algorithm:
  1. For each planning zone, select matching parcels by DLBM preference
  2. Check KG constraints after each allocation decision
  3. Re-allocate parcels that violate constraints
  4. Fill remaining area from nearest compatible parcels (spatial tiebreaker)

This produces allocations DIFFERENT from simple DLBM reclassification
because constraints can force reassignment of parcels that would otherwise
be classified differently.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple
from collections import defaultdict

from app.utils.logger import get_logger

logger = get_logger(__name__)

# Priority order for assigning parcels: DLBM directly matching zone type
# Imported from colors.py ZONE_TYPE_TO_DLBMS (single source of truth)
from ..zone_schema import ZONE_TYPE_TO_DLBMS as DLBM_PREFERENCE, PROTECTED_DLBM_CODES, CONSTRUCTION_ZONE_TYPES

# Precomputed DLBM category sets (avoid rebuilding per _preference_cost call)
_AGRI_DLBM_SET: set = set()
_ECO_DLBM_SET: set = set()
for _zt, _dlbms in DLBM_PREFERENCE.items():
    if _zt == "农业用地":
        _AGRI_DLBM_SET.update(_dlbms)
    if _zt in ("生态绿地", "水域"):
        _ECO_DLBM_SET.update(_dlbms)

# Constraints translate to parcel-level rules
CONSTRAINT_NAMES = {
    "construction_cap": {
        "zones": ["居住用地", "产业用地", "公共服务用地", "交通用地", "商业用地"],
        "field": "construction_area_ha",
    },
    "farmland_min": {
        "zones": ["农业用地"],
        "field": "farmland_area_ha",
    },
    "ecological_redline_min": {
        "zones": ["生态绿地"],
        "field": "ecological_redline_ha",
    },
    "forest_land_min": {
        "zones": ["生态绿地"],
        "field": "forest_land_ha",
    },
}


class ConstraintDrivenAllocator:
    """Assign 660 parcels to 7 planning zones respecting KG constraints.

    Algorithm:
      1. Initialize all parcels as 'unassigned'
      2. For each zone (priority: protected first → construction last):
         a. Select preferred parcels (DLBM match)
         b. If target exceeded → trim farthest parcels
         c. If target undershot → expand to adjacent unassigned parcels
      3. Check constraints:
         - construction_cap: total construction ≤ limit
         - farmland_min: total farmland ≥ minimum
         - ecological_redline_min: ecological ≥ minimum
      4. Re-allocate violating parcels
      5. Repeat until stable or max iterations
    """

    def __init__(self, adjacency_map: Optional[Dict[str, set]] = None):
        self.assignments: Dict[str, str] = {}  # bsm → zone_type
        self.zone_areas: Dict[str, float] = defaultdict(float)
        self.constraints: List[Dict] = []
        self.adjacency_map: Dict[str, set] = adjacency_map or {}

    def solve(
        self,
        landuse_geojson: Dict[str, Any],
        targets: Dict[str, float],
        constraints: Optional[List[Dict]] = None,
        kg=None,
        mode: str = "greedy",
        protection_zones: Optional[Dict[str, Dict[str, Any]]] = None,
        adjacency_graph: Optional[Any] = None,
        adjacency_weight: float = 0.5,
        change_penalty_weight: float = 0.3,
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """Run constraint-driven allocation.

        Args:
            landuse_geojson: Current land use parcels (FeatureCollection)
            targets: {zone_type_or_planning_zone: target_area_ha}
                     Accepts both 7-class zone_type keys (居住用地, 农业用地, etc.)
                     and 4-class planning zone keys (农田保护区, etc.)
            constraints: list of constraint dicts from KG
            kg: Optional PlanningKG for spatial queries
            mode: "greedy" (default) or "mip" (PuLP-based MIP)
            protection_zones: Dict of protection zone GeoJSONs by name
            adjacency_graph: Optional AdjacencyGraph for MIP spatial constraints
            adjacency_weight: Weight for adjacency compatibility in MIP mode
            change_penalty_weight: Weight for change-from-current penalty in MIP mode

        Returns:
            GeoJSON FeatureCollection with 'assigned_zone' property on each feature.
            When planning zone targets are used, assigned_zone is remapped to
            4-class planning zone names (农田保护区/村庄建设区/生态保护区/一般农业区).
        """
        if mode == "mip":
            from .mip_allocator import MIPZoneAllocator
            allocator = MIPZoneAllocator()
            return allocator.solve(
                landuse_geojson, targets, constraints, kg,
                adjacency_graph=adjacency_graph,
                adjacency_weight=adjacency_weight,
                change_penalty_weight=change_penalty_weight,
            )

        # Reset state from any prior solve() call
        self.assignments = {}
        self.zone_areas = defaultdict(float)
        self.constraints = constraints or []

        # Convert protection zones to hard constraints
        if protection_zones:
            for zone_name, geojson in protection_zones.items():
                if geojson and geojson.get("features"):
                    self.constraints.append({
                        "id": f"protection_{zone_name}",
                        "op": "forbidden",
                        "zone_name": zone_name,
                        "geojson": geojson,
                    })

        features = landuse_geojson.get("features", [])
        if not features:
            return landuse_geojson, {}

        from ..zone_generator import resolve_zone_type_for_dlbm
        from ..zone_schema import get_zone_type_for_planned_dlbm
        from ...utils.geojson_utils import build_parcel_index
        from .planning_zone_mapper import (
            PLANNING_ZONE_TO_ZONE_TYPES,
            map_planning_zone_targets_to_zone_types,
            remap_assigned_zones,
        )

        # Auto-detect planning zone targets and convert to zone_type
        uses_planning_zones = any(
            k in PLANNING_ZONE_TO_ZONE_TYPES for k in targets
        )
        if uses_planning_zones:
            zone_type_targets = map_planning_zone_targets_to_zone_types(targets, landuse_geojson)
        else:
            zone_type_targets = targets

        # Build parcel index using shared utility
        parcel_db, _dup = build_parcel_index(landuse_geojson, zone_type_fn=resolve_zone_type_for_dlbm)

        total_area = sum(p["area_ha"] for p in parcel_db.values())
        logger.info(
            f"[Allocator] {len(parcel_db)} parcels, total_area={total_area:.1f}ha, "
            f"targets={len(zone_type_targets)} zones, constraints={len(self.constraints)}"
        )

        # Step 1: Greedy preferred assignment
        self._greedy_assign(parcel_db, zone_type_targets)

        # Step 2: Constraint check and re-allocation
        self._enforce_constraints(parcel_db, zone_type_targets)

        # Step 3: Fill unassigned
        self._fill_unassigned(parcel_db, zone_type_targets)

        # Build output GeoJSON
        output_features = []
        for composite_key, info in parcel_db.items():
            ft = dict(info["feature"])
            assigned = self.assignments.get(composite_key, info["current_zone"])
            ft.setdefault("properties", {})
            ft["properties"]["assigned_zone"] = assigned
            ft["properties"]["original_zone"] = info["current_zone"]
            ft["properties"]["changed"] = assigned != info["current_zone"]
            ft["properties"]["area_ha"] = info["area_ha"]
            ft["properties"]["composite_key"] = composite_key
            ft["properties"]["bsm_raw"] = info["bsm_bare"]
            output_features.append(ft)

        # Remap assigned_zone from 7-class zone_type to 4-class planning zone
        if uses_planning_zones:
            remap_assigned_zones(output_features)

        # Log statistics
        changed = sum(1 for ck in self.assignments
                      if self.assignments[ck] != parcel_db[ck]["current_zone"])
        logger.info(
            f"[Allocator] Complete: {len(output_features)} features, "
            f"{changed} changed ({changed/len(output_features)*100:.1f}%)"
        )

        # Zone area summary
        zone_summary = defaultdict(float)
        for ck, zt in self.assignments.items():
            zone_summary[zt] += parcel_db[ck]["area_ha"]
        for zt in sorted(zone_summary.keys()):
            target = targets.get(zt, 0)
            logger.info(f"  {zt}: {zone_summary[zt]:.1f}ha (target={target:.1f}ha)")

        return {"type": "FeatureCollection", "features": output_features}, {"mode": "greedy"}

    def _greedy_assign(self, parcel_db: dict, targets: dict):
        """Assign parcels to their preferred zone type by DLBM match.

        Protected zones (farmland, ecology) get priority to ensure minimums met.
        """
        # Order: protected zones first (hard minimums), then construction zones
        protected_first = ["农业用地", "生态绿地", "水域"]
        construction = ["居住用地", "产业用地", "公共服务用地", "交通用地", "商业用地"]
        zone_order = [z for z in protected_first if z in targets] + \
                     [z for z in construction if z in targets] + \
                     [z for z in targets if z not in protected_first + construction]

        for zone_type in zone_order:
            target = targets[zone_type]
            preferred_dlbms = DLBM_PREFERENCE.get(zone_type, [])

            # Find unassigned preferred parcels
            candidates = []
            for bsm, info in parcel_db.items():
                if bsm in self.assignments:
                    continue
                if info["dlbm"] in preferred_dlbms:
                    # Adjacency score: count of adjacent parcels already in this zone
                    adj_score = 0
                    if self.adjacency_map and bsm in self.adjacency_map:
                        for neighbor in self.adjacency_map[bsm]:
                            if self.assignments.get(neighbor) == zone_type:
                                adj_score += 1
                    candidates.append((bsm, info["area_ha"], adj_score))

            # Sort by adjacency score descending (compact zones), then area descending
            candidates.sort(key=lambda x: (-x[2], -x[1]))

            # Assign until target met (or slightly over)
            assigned_area = 0.0
            for bsm, area, _adj_score in candidates:
                if assigned_area >= target * 1.05:  # Allow 5% overshoot
                    break
                self.assignments[bsm] = zone_type
                assigned_area += area

            self.zone_areas[zone_type] = assigned_area

        # Overflow stage: assign unassigned parcels to zones still under 90% of target
        for zone_type in zone_order:
            target = targets[zone_type]
            current = self.zone_areas.get(zone_type, 0)
            if current >= target * 0.9:
                continue
            shortfall = target - current
            candidates = []
            for bsm, info in parcel_db.items():
                if bsm in self.assignments:
                    continue
                cost = self._preference_cost(info["dlbm"], zone_type)
                candidates.append((bsm, info["area_ha"], cost))
            candidates.sort(key=lambda x: x[2])
            for bsm, area, cost in candidates:
                if shortfall <= 0:
                    break
                if cost >= 1000:
                    break
                self.assignments[bsm] = zone_type
                self.zone_areas[zone_type] = \
                    self.zone_areas.get(zone_type, 0) + area
                shortfall -= area

    def _preference_cost(self, dlbm: str, zone_type: str) -> float:
        """Return DLBM preference cost for assigning dlbm to zone_type.

        Cost 0 = preferred DLBM, 5 = same category, 10-15 = cross-category,
        1000 = absolutely forbidden (non-agricultural red line).
        """
        # Hard constraint: protected DLBM cannot go to construction zones
        if dlbm in PROTECTED_DLBM_CODES and zone_type in CONSTRUCTION_ZONE_TYPES:
            return 1000.0

        preferred = DLBM_PREFERENCE.get(zone_type, [])
        if dlbm in preferred:
            return 0.0
        # Check if DLBM belongs to the same broad category
        if zone_type == "农业用地" and dlbm in _ECO_DLBM_SET:
            return 10.0
        if zone_type in ("生态绿地", "水域") and dlbm in _AGRI_DLBM_SET:
            return 10.0
        return 15.0

    def _enforce_constraints(self, parcel_db: dict, targets: dict):
        """Check KG constraints and re-allocate violating parcels."""
        for constraint in self.constraints:
            cid = constraint.get("id", "")
            op = constraint.get("op", "")
            value_str = constraint.get("value", "0")
            try:
                limit = float(value_str)
            except (ValueError, TypeError):
                continue

            # Find which zones this constraint applies to
            constrained_zones = self._get_constrained_zones(cid)

            # Calculate current total
            current_total = sum(
                self.zone_areas.get(zt, 0) for zt in constrained_zones
            )

            if op == "<=" and current_total > limit:
                # Need to reduce: find parcels in constrained zones and reassign
                excess = current_total - limit
                logger.info(f"[Allocator] Constraint violation: {cid} "
                            f"({current_total:.2f} > {limit}), excess={excess:.2f}ha")

                # Find the smallest parcels in constrained zones to reassign
                candidates = []
                for bsm, zt in self.assignments.items():
                    if zt in constrained_zones and bsm in parcel_db:
                        candidates.append((bsm, parcel_db[bsm]["area_ha"]))

                candidates.sort(key=lambda x: x[1])  # Smallest first

                # Reassign to non-constrained zones (prefer agriculture/ecology)
                reassigned_area = 0.0
                for bsm, area in candidates:
                    if reassigned_area >= excess:
                        break
                    old_zone = self.assignments.get(bsm, parcel_db[bsm]["current_zone"])
                    current_zone = parcel_db[bsm]["current_zone"]
                    if current_zone not in constrained_zones:
                        new_zone = current_zone
                    else:
                        new_zone = "农业用地"  # Safe fallback
                    self.assignments[bsm] = new_zone
                    self.zone_areas[old_zone] = self.zone_areas.get(old_zone, 0) - area
                    self.zone_areas[new_zone] = self.zone_areas.get(new_zone, 0) + area
                    reassigned_area += area

            elif op == ">=" and current_total < limit:
                # Need to increase: find non-constrained parcels to add
                shortfall = limit - current_total
                logger.info(f"[Allocator] Constraint shortfall: {cid} "
                            f"({current_total:.2f} < {limit}), need={shortfall:.2f}ha")

                for bsm, info in parcel_db.items():
                    if shortfall <= 0:
                        break
                    if bsm not in self.assignments:
                        zone_type = constrained_zones[0] if constrained_zones else "农业用地"
                        self.assignments[bsm] = zone_type
                        self.zone_areas[zone_type] = \
                            self.zone_areas.get(zone_type, 0) + info["area_ha"]
                        shortfall -= info["area_ha"]

    def _get_constrained_zones(self, cid: str) -> List[str]:
        """Map constraint ID to affected zone types."""
        for key, info in CONSTRAINT_NAMES.items():
            if key in cid:
                return info["zones"]
        return ["农业用地"]  # Default safe zone

    def _fill_unassigned(self, parcel_db: dict, targets: dict):
        """Assign remaining unassigned parcels, respecting DLBM-zone compatibility."""
        unassigned = [bsm for bsm in parcel_db if bsm not in self.assignments]
        if not unassigned:
            return

        # Compute area gaps per zone (positive = under target)
        gaps = {}
        for zone_type, target in targets.items():
            current = self.zone_areas.get(zone_type, 0)
            if current < target:
                gaps[zone_type] = target - current

        # Sort zones by gap descending (largest deficit first)
        sorted_zones = sorted(gaps.keys(), key=lambda z: -gaps[z])

        for bsm in unassigned:
            info = parcel_db[bsm]
            dlbm = info["dlbm"]
            assigned = False
            # Try zones with largest gap first, but check DLBM compatibility
            for zone_type in sorted_zones:
                if gaps.get(zone_type, 0) <= 0:
                    continue
                # Hard constraint: protected DLBM cannot go to construction
                if dlbm in PROTECTED_DLBM_CODES and zone_type in CONSTRUCTION_ZONE_TYPES:
                    continue
                cost = self._preference_cost(dlbm, zone_type)
                if cost >= 1000:
                    continue
                self.assignments[bsm] = zone_type
                self.zone_areas[zone_type] = \
                    self.zone_areas.get(zone_type, 0) + info["area_ha"]
                gaps[zone_type] -= info["area_ha"]
                assigned = True
                break
            if not assigned:
                # Fallback: assign to DLBM default zone (never cross red lines)
                current_zone = info["current_zone"]
                self.assignments[bsm] = current_zone
                self.zone_areas[current_zone] = \
                    self.zone_areas.get(current_zone, 0) + info["area_ha"]
