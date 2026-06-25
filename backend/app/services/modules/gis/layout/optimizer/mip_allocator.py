"""PuLP-based Mixed Integer Programming zone allocator.

Solves the zone assignment problem as a true MIP:
  Variables: x[i][z] = 1 if parcel i assigned to zone z
  Objective:  minimize total area deviation from targets
  Constraints:
    - Each parcel assigned to exactly one zone
    - Zone areas within target ± tolerance (soft via objective)
    - Protected DLBM parcels cannot go to construction zone
    - DLBM preference encoded as cost coefficient
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from collections import defaultdict

from app.utils.logger import get_logger

logger = get_logger(__name__)

# DLBM → preferred zone type mapping (lower cost = stronger preference)
DLBM_ZONE_PREFERENCE: Dict[str, Dict[str, int]] = {
    # Farmland DLBMs → strongly prefer agriculture
    "0110": {"农业用地": 0, "生态绿地": 5, "居住用地": 50, "产业用地": 50},
    "0120": {"农业用地": 0, "生态绿地": 5, "居住用地": 50, "产业用地": 50},
    "0130": {"农业用地": 0, "生态绿地": 5, "居住用地": 50, "产业用地": 50},
    "0100": {"农业用地": 0, "生态绿地": 5, "居住用地": 50, "产业用地": 50},
    "0200": {"农业用地": 0, "生态绿地": 5, "居住用地": 50, "产业用地": 50},
    "0210": {"农业用地": 0, "生态绿地": 5, "居住用地": 50, "产业用地": 50},
    "0220": {"农业用地": 0, "生态绿地": 5, "居住用地": 50, "产业用地": 50},
    "1100": {"农业用地": 0, "生态绿地": 5, "居住用地": 50, "产业用地": 50},
    "1200": {"农业用地": 0, "生态绿地": 5, "居住用地": 50, "产业用地": 50},
    "1510": {"农业用地": 0, "生态绿地": 5, "居住用地": 50, "产业用地": 50},
    "1180": {"农业用地": 0, "生态绿地": 5, "居住用地": 50, "产业用地": 50},
    "2270": {"农业用地": 0, "生态绿地": 5, "居住用地": 50, "产业用地": 50},
    # Construction DLBMs → strongly prefer construction zones
    "2121": {"居住用地": 0, "公共服务用地": 5, "产业用地": 10, "农业用地": 30},
    "2030": {"居住用地": 0, "公共服务用地": 5, "产业用地": 10, "农业用地": 30},
    "2122": {"公共服务用地": 0, "居住用地": 5, "产业用地": 10, "农业用地": 30},
    "2125": {"公共服务用地": 0, "居住用地": 5, "产业用地": 10, "农业用地": 30},
    "2124": {"产业用地": 0, "居住用地": 5, "公共服务用地": 10, "农业用地": 30},
    "2126": {"交通用地": 0, "居住用地": 10, "农业用地": 30},
    # Ecological DLBMs → strongly prefer ecology
    "1340": {"生态绿地": 0, "农业用地": 5, "居住用地": 50, "产业用地": 50},
    "1350": {"生态绿地": 0, "农业用地": 5, "居住用地": 50, "产业用地": 50},
    "0310": {"生态绿地": 0, "农业用地": 5, "居住用地": 50, "产业用地": 50},
    "0330": {"生态绿地": 0, "农业用地": 5, "居住用地": 50, "产业用地": 50},
    "1400": {"生态绿地": 0, "农业用地": 5, "居住用地": 50, "产业用地": 50},
    "0300": {"生态绿地": 0, "农业用地": 5, "居住用地": 50, "产业用地": 50},
    "0400": {"生态绿地": 0, "农业用地": 5, "居住用地": 50, "产业用地": 50},
    # Water
    "3100": {"水域": 0, "生态绿地": 5, "农业用地": 20},
    "1110": {"水域": 0, "生态绿地": 5, "农业用地": 20},
    "1140": {"水域": 0, "生态绿地": 5, "农业用地": 20},
    # Roads
    "2200": {"交通用地": 0, "居住用地": 10, "农业用地": 20},
    "1040": {"交通用地": 0, "居住用地": 10, "农业用地": 20},
    "1000": {"交通用地": 0, "居住用地": 10, "农业用地": 20},
    # Commercial
    "0500": {"商业用地": 0, "居住用地": 5, "产业用地": 10, "农业用地": 30},
    # Industry
    "0600": {"产业用地": 0, "居住用地": 10, "农业用地": 30},
    "0610": {"产业用地": 0, "居住用地": 10, "农业用地": 30},
    "0620": {"产业用地": 0, "居住用地": 10, "农业用地": 30},
    # Public services
    "0800": {"公共服务用地": 0, "居住用地": 5, "产业用地": 10, "农业用地": 30},
    "0900": {"公共服务用地": 0, "居住用地": 5, "产业用地": 10, "农业用地": 30},
}

# DLBM codes that are protected (farmland/ecological) — cannot go to construction
PROTECTED_DLBM_CODES = {
    "0110", "0120", "0130", "0100", "0200", "0210", "0220",
    "1100", "1200", "1510", "1180", "2270",
    "1340", "1350", "0310", "0330", "1400", "0300", "0400",
}

CONSTRUCTION_ZONE_TYPES = {"居住用地", "产业用地", "公共服务用地", "交通用地", "商业用地"}

# Default cost for DLBM-zone pairs not in preference table
DEFAULT_PREFERENCE_COST = 15


class MIPZoneAllocator:
    """PuLP-based MIP zone allocator.

    Solves:
      min  Σ_z (dev_pos_z + dev_neg_z) * AREA_WEIGHT
         + Σ_i Σ_z x[i][z] * preference_cost[i][z]

    s.t.
      Σ_z x[i][z] = 1                    for all i (each parcel assigned once)
      Σ_i area[i] * x[i][z] - target[z] = dev_pos_z - dev_neg_z   (area deviation)
      x[i][z] = 0                         for protected i → construction z
      x[i][z] ∈ {0, 1}
      dev_pos_z, dev_neg_z ≥ 0
    """

    def solve(
        self,
        landuse_geojson: Dict[str, Any],
        targets: Dict[str, float],
        constraints: Optional[List[Dict]] = None,
        kg=None,
    ) -> Dict[str, Any]:
        """Run MIP allocation.

        Args:
            landuse_geojson: Current land use parcels (FeatureCollection)
            targets: {zone_type: target_area_ha}
            constraints: KG constraint dicts (used for hard bounds)
            kg: Optional PlanningKG

        Returns:
            GeoJSON FeatureCollection with 'assigned_zone' on each feature
        """
        try:
            import pulp
        except ImportError:
            logger.error("[MIP] PuLP not installed, falling back to greedy")
            from .mip_solver import ConstraintDrivenAllocator
            return ConstraintDrivenAllocator().solve(
                landuse_geojson, targets, constraints, kg, mode="greedy"
            )

        features = landuse_geojson.get("features", [])
        if not features:
            return landuse_geojson

        from ..zone_generator import resolve_zone_type_for_dlbm

        # Build parcel data
        parcels = []
        for ft in features:
            props = ft.get("properties", {})
            bsm = str(props.get("BSM", ""))
            if not bsm:
                continue
            area = (props.get("DLMJ", 0) or props.get("SHAPE_Area", 0)) / 10000
            dlbm = str(props.get("DLBM", "")).strip()
            current_zone = resolve_zone_type_for_dlbm(dlbm)
            parcels.append({
                "bsm": bsm,
                "area_ha": area,
                "dlbm": dlbm,
                "current_zone": current_zone,
                "feature": ft,
            })

        zone_types = list(targets.keys())
        n_parcels = len(parcels)
        n_zones = len(zone_types)

        if n_parcels == 0 or n_zones == 0:
            return landuse_geojson

        logger.info(
            f"[MIP] Building model: {n_parcels} parcels × {n_zones} zones = "
            f"{n_parcels * n_zones} binary variables"
        )

        # ---- Build PuLP model ----
        prob = pulp.LpProblem("ZoneAllocation", pulp.LpMinimize)

        # Binary variables: x[i][z] = 1 if parcel i assigned to zone z
        x = {}
        for i, p in enumerate(parcels):
            for j, zt in enumerate(zone_types):
                # Protected parcels cannot go to construction zones
                if p["dlbm"] in PROTECTED_DLBM_CODES and zt in CONSTRUCTION_ZONE_TYPES:
                    continue
                x[i, j] = pulp.LpVariable(f"x_{i}_{j}", cat="Binary")

        # Deviation variables: dev_pos[z] and dev_neg[z]
        dev_pos = {}
        dev_neg = {}
        for j, zt in enumerate(zone_types):
            dev_pos[j] = pulp.LpVariable(f"dev_pos_{j}", lowBound=0)
            dev_neg[j] = pulp.LpVariable(f"dev_neg_{j}", lowBound=0)

        # ---- Constraints ----

        # C1: Each parcel assigned to exactly one zone
        for i, p in enumerate(parcels):
            assigned_vars = [x[i, j] for j in range(n_zones) if (i, j) in x]
            if assigned_vars:
                prob += pulp.lpSum(assigned_vars) == 1, f"assign_{i}"

        # C2: Area deviation definition
        # Σ_i area[i] * x[i][z] - target[z] = dev_pos[z] - dev_neg[z]
        for j, zt in enumerate(zone_types):
            target = targets[zt]
            area_terms = []
            for i, p in enumerate(parcels):
                if (i, j) in x:
                    area_terms.append(p["area_ha"] * x[i, j])
            if area_terms:
                prob += (
                    pulp.lpSum(area_terms) - target == dev_pos[j] - dev_neg[j],
                    f"deviation_{j}"
                )

        # C3: Hard constraints from KG (if provided)
        if constraints:
            self._add_hard_constraints(pulp, prob, x, parcels, zone_types, constraints, targets)

        # ---- Objective ----
        # Minimize: area deviation + DLBM preference cost
        AREA_WEIGHT = 10.0  # Weight for area deviation vs preference cost

        obj_terms = []

        # Area deviation penalty
        for j in range(n_zones):
            obj_terms.append(AREA_WEIGHT * dev_pos[j])
            obj_terms.append(AREA_WEIGHT * dev_neg[j])

        # DLBM preference cost
        for i, p in enumerate(parcels):
            for j, zt in enumerate(zone_types):
                if (i, j) in x:
                    cost = self._get_preference_cost(p["dlbm"], zt)
                    obj_terms.append(cost * x[i, j])

        prob += pulp.lpSum(obj_terms)

        # ---- Solve ----
        solver = pulp.PULP_CBC_CMD(msg=0, timeLimit=30)
        status = prob.solve(solver)

        if pulp.LpStatus[status] != "Optimal":
            logger.warning(
                f"[MIP] Solver status: {pulp.LpStatus[status]}, "
                f"using best feasible solution"
            )

        # ---- Extract solution ----
        assignments = {}
        zone_areas = defaultdict(float)
        for i, p in enumerate(parcels):
            best_j = None
            best_val = 0.0
            for j, zt in enumerate(zone_types):
                if (i, j) in x:
                    val = pulp.value(x[i, j]) or 0.0
                    if val > best_val:
                        best_val = val
                        best_j = j
            if best_j is not None:
                assigned_zt = zone_types[best_j]
            else:
                assigned_zt = p["current_zone"]
            assignments[p["bsm"]] = assigned_zt
            zone_areas[assigned_zt] += p["area_ha"]

        # Build output GeoJSON
        output_features = []
        for p in parcels:
            ft = dict(p["feature"])
            assigned = assignments.get(p["bsm"], p["current_zone"])
            ft.setdefault("properties", {})
            ft["properties"]["assigned_zone"] = assigned
            ft["properties"]["original_zone"] = p["current_zone"]
            ft["properties"]["changed"] = assigned != p["current_zone"]
            ft["properties"]["area_ha"] = p["area_ha"]
            output_features.append(ft)

        # Log results
        changed = sum(1 for p in parcels
                      if assignments.get(p["bsm"], p["current_zone"]) != p["current_zone"])
        total_deviation = sum(
            abs(zone_areas.get(zt, 0) - targets.get(zt, 0))
            for zt in zone_types
        )
        logger.info(
            f"[MIP] Complete: {len(output_features)} features, "
            f"{changed} changed ({changed/len(output_features)*100:.1f}%), "
            f"total_deviation={total_deviation:.1f}ha"
        )
        for zt in sorted(zone_areas.keys()):
            target = targets.get(zt, 0)
            actual = zone_areas[zt]
            dev = actual - target
            logger.info(f"  {zt}: {actual:.1f}ha (target={target:.1f}ha, dev={dev:+.1f}ha)")

        return {"type": "FeatureCollection", "features": output_features}

    @staticmethod
    def _get_preference_cost(dlbm: str, zone_type: str) -> int:
        """Get DLBM-zone preference cost. Lower = stronger preference."""
        prefs = DLBM_ZONE_PREFERENCE.get(dlbm)
        if prefs:
            return prefs.get(zone_type, DEFAULT_PREFERENCE_COST)
        return DEFAULT_PREFERENCE_COST

    @staticmethod
    def _add_hard_constraints(
        pulp_mod,
        prob,
        x: Dict,
        parcels: List[Dict],
        zone_types: List[str],
        constraints: List[Dict],
        targets: Dict[str, float],
    ):
        """Add KG-derived hard constraints to the MIP model."""
        for c in constraints:
            cid = c.get("id", "")
            op = c.get("operator", c.get("op", ""))
            try:
                value = float(c.get("value", 0))
            except (ValueError, TypeError):
                continue

            # Construction cap: Σ construction zones ≤ limit
            if "construction" in cid and op in ("<=", "lte"):
                construction_indices = [
                    j for j, zt in enumerate(zone_types)
                    if zt in CONSTRUCTION_ZONE_TYPES
                ]
                for j in construction_indices:
                    area_terms = []
                    for i, p in enumerate(parcels):
                        if (i, j) in x:
                            area_terms.append(p["area_ha"] * x[i, j])
                    if area_terms:
                        prob += (
                            pulp_mod.lpSum(area_terms) <= value,
                            f"kg_construction_cap_{j}"
                        )

            # Farmland minimum: Σ agriculture zones ≥ limit
            elif "farmland" in cid and op in (">=", "gte"):
                ag_indices = [
                    j for j, zt in enumerate(zone_types)
                    if zt == "农业用地"
                ]
                for j in ag_indices:
                    area_terms = []
                    for i, p in enumerate(parcels):
                        if (i, j) in x:
                            area_terms.append(p["area_ha"] * x[i, j])
                    if area_terms:
                        prob += (
                            pulp_mod.lpSum(area_terms) >= value,
                            f"kg_farmland_min_{j}"
                        )

            # Ecological minimum
            elif "ecological" in cid and op in (">=", "gte"):
                eco_indices = [
                    j for j, zt in enumerate(zone_types)
                    if zt == "生态绿地"
                ]
                for j in eco_indices:
                    area_terms = []
                    for i, p in enumerate(parcels):
                        if (i, j) in x:
                            area_terms.append(p["area_ha"] * x[i, j])
                    if area_terms:
                        prob += (
                            pulp_mod.lpSum(area_terms) >= value,
                            f"kg_eco_min_{j}"
                        )
