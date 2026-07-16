"""PuLP-based Mixed Integer Programming zone allocator.

Solves the zone assignment problem as a true MIP:
  Variables: x[i][z] = 1 if parcel i assigned to planning zone z
  Objective:  minimize total area deviation from targets
  Constraints:
    - Each parcel assigned to exactly one planning zone
    - Zone areas within target ± tolerance (soft via objective)
    - Protected DLBM parcels cannot go to construction zone
    - DLBM preference encoded as cost coefficient

Planning zone classification (based on GB/T 21010 + 三区三线 national standard):
  - 生态保护区 (Ecological Protection Zone): forests, wetlands, water bodies
  - 农田保护区 (Farmland Protection Zone): permanent basic farmland (耕地 01)
  - 村庄建设区 (Village Construction Zone): residential, industrial, public, transport, commercial
  - 一般农业区 (General Agricultural Zone): gardens, general cropland, facility agriculture

DLBM codes map DIRECTLY to planning zones — no intermediate zone_type layer.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
from collections import defaultdict

from app.utils.logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# DLBM → Planning Zone: import from single source (schema.py)
# ---------------------------------------------------------------------------
from ...schema import DLBM_TO_PLANNING_ZONE, PROTECTED_DLBM_CODES
from ...schema.encodings import dlbm_to_planning_zone

# Cross-zone preference cost matrix (symmetric-ish)
# Same zone = 0, compatible zones = low cost, forbidden zones = high cost
CROSS_ZONE_COST: Dict[tuple, int] = {
    # 农田↔一般农业: compatible (both agricultural)
    ("农田保护区", "一般农业区"): 3, ("一般农业区", "农田保护区"): 3,
    # 生态保护区↔生态控制区: compatible (both ecological)
    ("生态保护区", "生态控制区"): 2, ("生态控制区", "生态保护区"): 2,
    # 生态保护区↔林业发展区: compatible (both ecological)
    ("生态保护区", "林业发展区"): 3, ("林业发展区", "生态保护区"): 3,
    # 生态控制区↔林业发展区: compatible
    ("生态控制区", "林业发展区"): 3, ("林业发展区", "生态控制区"): 3,
    # 生态↔一般农业: somewhat compatible
    ("生态保护区", "一般农业区"): 5, ("一般农业区", "生态保护区"): 5,
    ("生态控制区", "一般农业区"): 5, ("一般农业区", "生态控制区"): 5,
    ("林业发展区", "一般农业区"): 4, ("一般农业区", "林业发展区"): 4,
    # 农田↔生态: moderate conflict
    ("农田保护区", "生态保护区"): 10, ("生态保护区", "农田保护区"): 10,
    ("农田保护区", "生态控制区"): 8, ("生态控制区", "农田保护区"): 8,
    ("农田保护区", "林业发展区"): 10, ("林业发展区", "农田保护区"): 10,
    # 建设↔一般农业: significant conflict
    ("村庄建设区", "一般农业区"): 30, ("一般农业区", "村庄建设区"): 30,
    # 建设↔农田: strong conflict (基本农田保护)
    ("村庄建设区", "农田保护区"): 40, ("农田保护区", "村庄建设区"): 40,
    # 建设↔生态: strongest conflict
    ("村庄建设区", "生态保护区"): 50, ("生态保护区", "村庄建设区"): 50,
    ("村庄建设区", "生态控制区"): 45, ("生态控制区", "村庄建设区"): 45,
    ("村庄建设区", "林业发展区"): 40, ("林业发展区", "村庄建设区"): 40,
}

# Construction planning zones
PLANNING_CONSTRUCTION_ZONES = {"村庄建设区"}

# Default cost for DLBM-zone pairs not in cross-zone matrix
DEFAULT_PREFERENCE_COST = 20


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
        adjacency_graph: Optional[Any] = None,
        adjacency_weight: float = 0.5,
        change_penalty_weight: float = 0.3,
    ) -> Tuple[Dict[str, Any], Any]:
        """Run MIP allocation.

        Returns:
            Tuple of (GeoJSON FeatureCollection, MIPTrace dict).
        """
        from ..trace import MIPTrace
        try:
            import pulp
        except ImportError:
            logger.error("[MIP] PuLP not installed, falling back to greedy")
            from .mip_solver import ConstraintDrivenAllocator
            greedy_result = ConstraintDrivenAllocator().solve(
                landuse_geojson, targets, constraints, kg, mode="greedy"
            )
            return greedy_result, MIPTrace(mode="greedy-fallback").model_dump()

        features = landuse_geojson.get("features", [])
        if not features:
            return landuse_geojson

        from ..zone_generator import resolve_zone_type_for_dlbm
        from ...utils.geojson_utils import build_parcel_index

        parcel_db, _dup = build_parcel_index(landuse_geojson, zone_type_fn=resolve_zone_type_for_dlbm)
        parcels = [
            {**info, "composite_key": key}
            for key, info in parcel_db.items()
        ]

        planning_zones = list(targets.keys())
        n_parcels = len(parcels)
        n_zones = len(planning_zones)

        if n_parcels == 0 or n_zones == 0:
            return landuse_geojson, MIPTrace().model_dump()

        logger.info(
            f"[MIP] Building model: {n_parcels} parcels × {n_zones} zones = "
            f"{n_parcels * n_zones} binary variables"
        )

        # ---- Build PuLP model ----
        prob = pulp.LpProblem("ZoneAllocation", pulp.LpMinimize)

        # Binary variables: x[i][z] = 1 if parcel i assigned to planning zone z
        x = {}
        for i, p in enumerate(parcels):
            for j, zt in enumerate(planning_zones):
                # Protected parcels cannot go to construction zones
                if p["dlbm"] in PROTECTED_DLBM_CODES and zt in PLANNING_CONSTRUCTION_ZONES:
                    continue
                x[i, j] = pulp.LpVariable(f"x_{i}_{j}", cat="Binary")

        # Deviation variables: dev_pos[z] and dev_neg[z]
        dev_pos = {}
        dev_neg = {}
        for j, zt in enumerate(planning_zones):
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
        for j, zt in enumerate(planning_zones):
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

        # ---- Objective ----
        # Minimize: area deviation + DLBM preference cost + change penalty + adjacency reward
        AREA_WEIGHT = 10.0

        obj_terms = []

        # 1. Area deviation penalty
        for j in range(n_zones):
            obj_terms.append(AREA_WEIGHT * dev_pos[j])
            obj_terms.append(AREA_WEIGHT * dev_neg[j])

        # C3: KG constraints (soft, with slack variables added to obj_terms)
        if constraints:
            self._add_hard_constraints(
                pulp, prob, x, parcels, planning_zones, constraints, targets, obj_terms
            )

        # 2. DLBM → planning zone preference cost (direct, no mapping)
        for i, p in enumerate(parcels):
            for j, zt in enumerate(planning_zones):
                if (i, j) in x:
                    cost = self._get_preference_cost(p["dlbm"], zt)
                    obj_terms.append(cost * x[i, j])

        # 3. Change penalty: penalize assigning parcel to a zone different from its native zone
        if change_penalty_weight > 0:
            for i, p in enumerate(parcels):
                native_zone = dlbm_to_planning_zone(p["dlbm"])
                for j, zt in enumerate(planning_zones):
                    if (i, j) in x and zt != native_zone:
                        if (p["dlbm"] in PROTECTED_DLBM_CODES
                                and zt in PLANNING_CONSTRUCTION_ZONES):
                            continue  # Already forbidden by variable exclusion
                        obj_terms.append(change_penalty_weight * x[i, j])

        # 4. Adjacency compatibility: reward same-zone neighbors via linearized auxiliary vars
        adj_index_pairs = []
        if adjacency_graph is not None and adjacency_weight > 0:
            adj_index_pairs = adjacency_graph.to_index_pairs()
            if adj_index_pairs:
                y = {}
                for pair_id, (i_idx, j_idx) in enumerate(adj_index_pairs):
                    for j, zt in enumerate(planning_zones):
                        if (i_idx, j) in x and (j_idx, j) in x:
                            y[pair_id, j] = pulp.LpVariable(
                                f"y_{pair_id}_{j}", cat="Binary"
                            )
                            prob += (
                                y[pair_id, j] <= x[i_idx, j],
                                f"lin1_{pair_id}_{j}"
                            )
                            prob += (
                                y[pair_id, j] <= x[j_idx, j],
                                f"lin2_{pair_id}_{j}"
                            )
                            prob += (
                                y[pair_id, j] >= x[i_idx, j] + x[j_idx, j] - 1,
                                f"lin3_{pair_id}_{j}"
                            )
                            obj_terms.append(-adjacency_weight * y[pair_id, j])

                logger.info(
                    f"[MIP] Adjacency: {len(adj_index_pairs)} pairs, "
                    f"{sum(1 for k in y)} auxiliary vars"
                )

        prob += pulp.lpSum(obj_terms)

        # ---- Solve ----
        has_adj = adjacency_graph is not None and adjacency_weight > 0
        time_limit = 120 if has_adj else 30
        solver = pulp.PULP_CBC_CMD(msg=0, timeLimit=time_limit, gapRel=0.05)
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
            for j, zt in enumerate(planning_zones):
                if (i, j) in x:
                    val = pulp.value(x[i, j]) or 0.0
                    if val > best_val:
                        best_val = val
                        best_j = j
            if best_j is not None:
                assigned_zt = planning_zones[best_j]
            else:
                assigned_zt = dlbm_to_planning_zone(p["dlbm"])
            assignments[p["composite_key"]] = assigned_zt
            zone_areas[assigned_zt] += p["area_ha"]

        # Build output GeoJSON
        output_features = []
        for p in parcels:
            ft = dict(p["feature"])
            assigned = assignments.get(p["composite_key"], dlbm_to_planning_zone(p["dlbm"]))
            native_zone = dlbm_to_planning_zone(p["dlbm"])
            ft.setdefault("properties", {})
            ft["properties"]["assigned_zone"] = assigned
            ft["properties"]["original_zone"] = p["current_zone"]
            ft["properties"]["changed"] = assigned != native_zone
            ft["properties"]["area_ha"] = p["area_ha"]
            ft["properties"]["composite_key"] = p["composite_key"]
            ft["properties"]["bsm_raw"] = p["bsm_bare"]
            output_features.append(ft)

        # Log results
        changed = sum(1 for p in parcels
                      if assignments.get(p["composite_key"], dlbm_to_planning_zone(p["dlbm"])) != dlbm_to_planning_zone(p["dlbm"]))
        total_deviation = sum(
            abs(zone_areas.get(zt, 0) - targets.get(zt, 0))
            for zt in planning_zones
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

        # Build MIPTrace
        solver_status = pulp.LpStatus[status]
        objective_value = pulp.value(prob.objective) or 0.0
        zone_deviations = {zt: zone_areas.get(zt, 0) - targets.get(zt, 0) for zt in planning_zones}

        # Collect KG slack values (variables named kg_sl_*)
        kg_slack_values = {}
        for v in prob.variables():
            if v.name.startswith("kg_sl_"):
                kg_slack_values[v.name] = pulp.value(v) or 0.0

        mip_trace = MIPTrace(
            mode="KG-driven" if constraints else "DLBM-only",
            solver_status=solver_status,
            variable_count=n_parcels * n_zones,
            binary_variable_count=len(x),
            objective_value=objective_value,
            time_limit_seconds=time_limit,
            zone_targets=dict(targets),
            zone_actual=dict(zone_areas),
            zone_deviations=zone_deviations,
            kg_slack_values=kg_slack_values,
            adjacency_pairs=len(adj_index_pairs),
            changed_parcels=changed,
            changed_pct=changed / len(parcels) * 100 if parcels else 0,
        )

        return {"type": "FeatureCollection", "features": output_features}, mip_trace.model_dump()

    @staticmethod
    def _get_preference_cost(dlbm: str, planning_zone: str) -> int:
        """Get DLBM→planning zone preference cost via cross-zone matrix.

        1. Look up DLBM's native zone from DLBM_TO_PLANNING_ZONE
        2. If same zone → cost 0
        3. If different → look up CROSS_ZONE_COST(native, target)
        4. Fallback → DEFAULT_PREFERENCE_COST
        """
        native_zone = DLBM_TO_PLANNING_ZONE.get(str(dlbm).strip())
        if native_zone is None:
            return DEFAULT_PREFERENCE_COST
        if native_zone == planning_zone:
            return 0
        return CROSS_ZONE_COST.get((native_zone, planning_zone), DEFAULT_PREFERENCE_COST)

    def _add_hard_constraints(
        self,
        pulp_mod,
        prob,
        x: Dict,
        parcels: List[Dict],
        planning_zones: List[str],
        constraints: List[Dict],
        targets: Dict[str, float],
        obj_terms: list,
    ):
        """Add KG-derived constraints as soft constraints with DLBM clipping.

        KG constraints from report text often conflict with actual DLBM areas.
        Strategy: clip values to DLBM-feasible bounds, then add as soft constraints
        (slack variables) rather than hard constraints to avoid infeasibility.
        """
        native_zone_areas: Dict[str, float] = defaultdict(float)
        for p in parcels:
            native_zone_areas[dlbm_to_planning_zone(p["dlbm"])] += p["area_ha"]

        KG_WEIGHT = 5.0
        kg_cidx = 0

        for c in constraints:
            cid = c.get("id", "")
            op = c.get("operator", c.get("op", ""))
            try:
                value = float(c.get("value", 0))
            except (ValueError, TypeError):
                continue

            # Construction cap: Σ 村庄建设区 ≤ limit (soft via slack)
            if "construction" in cid and op in ("<=", "lte"):
                max_construction = native_zone_areas.get("村庄建设区", 0) * 3
                value = min(value, max_construction)
                construction_idx = next(
                    (j for j, zt in enumerate(planning_zones)
                     if zt in PLANNING_CONSTRUCTION_ZONES), None
                )
                if construction_idx is None:
                    continue
                area_terms = [
                    p["area_ha"] * x[i, construction_idx]
                    for i, p in enumerate(parcels)
                    if (i, construction_idx) in x
                ]
                if area_terms:
                    sl = pulp_mod.LpVariable(f"kg_sl_constr_{kg_cidx}", lowBound=0)
                    prob += (
                        pulp_mod.lpSum(area_terms) <= value + sl,
                        f"kg_construction_cap_{kg_cidx}"
                    )
                    obj_terms.append(KG_WEIGHT * sl)
                    kg_cidx += 1

            # Farmland minimum: Σ 农田保护区 + 一般农业区 ≥ limit (soft via slack)
            elif "farmland" in cid and op in (">=", "gte"):
                max_farmland = (
                    native_zone_areas.get("农田保护区", 0)
                    + native_zone_areas.get("一般农业区", 0)
                )
                value = min(value, max_farmland)
                if value <= 0:
                    continue
                ag_indices = [
                    j for j, zt in enumerate(planning_zones)
                    if zt in ("农田保护区", "一般农业区")
                ]
                area_terms = []
                for j in ag_indices:
                    for i, p in enumerate(parcels):
                        if (i, j) in x:
                            area_terms.append(p["area_ha"] * x[i, j])
                if area_terms:
                    sl = pulp_mod.LpVariable(f"kg_sl_farm_{kg_cidx}", lowBound=0)
                    prob += (
                        pulp_mod.lpSum(area_terms) + sl >= value,
                        f"kg_farmland_min_{kg_cidx}"
                    )
                    obj_terms.append(KG_WEIGHT * sl)
                    kg_cidx += 1

            # Ecological minimum: Σ 生态保护区 ≥ limit (soft via slack)
            elif "ecological" in cid and op in (">=", "gte"):
                max_eco = native_zone_areas.get("生态保护区", 0)
                value = min(value, max_eco)
                if value <= 0:
                    continue
                eco_indices = [
                    j for j, zt in enumerate(planning_zones)
                    if zt == "生态保护区"
                ]
                area_terms = []
                for j in eco_indices:
                    for i, p in enumerate(parcels):
                        if (i, j) in x:
                            area_terms.append(p["area_ha"] * x[i, j])
                if area_terms:
                    sl = pulp_mod.LpVariable(f"kg_sl_eco_{kg_cidx}", lowBound=0)
                    prob += (
                        pulp_mod.lpSum(area_terms) + sl >= value,
                        f"kg_eco_min_{kg_cidx}"
                    )
                    obj_terms.append(KG_WEIGHT * sl)
                    kg_cidx += 1
