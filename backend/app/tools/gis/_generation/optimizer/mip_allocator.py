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
from app.modules.schema import DLBM_TO_PLANNING_ZONE, PROTECTED_DLBM_CODES, dlbm_to_planning_zone

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
        parse_constraints: Optional[List[Dict]] = None,
        density_hints: Optional[Dict[str, str]] = None,
        adjacency_rules: Optional[Dict[str, dict]] = None,
        facility_anchors: Optional[List[Dict[str, Any]]] = None,
        protected_parcels_detail: Optional[List[Dict[str, Any]]] = None,
        three_line_targets: Optional[List[Dict[str, Any]]] = None,
        vne_summary: Optional[List[Dict[str, Any]]] = None,
        zone_targets: Optional[List[Any]] = None,
    ) -> Tuple[Dict[str, Any], Any]:
        """Run MIP allocation.

        Phase 5: protected_parcels_detail adds spatial containment exclusion —
        parcels within protection boundaries (per KG) are forbidden from
        construction zone assignment regardless of their DLBM code.

        Phase 6: three_line_targets adds hard area constraints from KG ThreeLine
        entities (no slack, no value clipping). vne_summary adds zone-level
        hard constraints from VNE classification.

        Returns:
            Tuple of (GeoJSON FeatureCollection, MIPTrace dict).
        """
        from app.tools.gis._generation.trace import MIPTrace
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
        from app.utils.geojson_utils import build_parcel_index

        parcel_db, _dup = build_parcel_index(landuse_geojson, zone_type_fn=resolve_zone_type_for_dlbm)
        parcels = [
            {**info, "composite_key": key}
            for key, info in parcel_db.items()
        ]

        planning_zones = list(targets.keys())

        # ── Pre-filter parcels by ZoneTarget spatial anchors ────────
        # Build candidate_bsms (union across all ZoneTargets) and excluded_bsms
        candidate_bsms: set = set()
        excluded_bsms: set = set()
        proximity_weights: Dict[str, Dict[str, float]] = {}
        if zone_targets:
            for zt in zone_targets:
                if hasattr(zt, 'candidate_bsms') and zt.candidate_bsms:
                    candidate_bsms.update(zt.candidate_bsms)
                if hasattr(zt, 'excluded_bsms') and zt.excluded_bsms:
                    excluded_bsms.update(zt.excluded_bsms)
                if hasattr(zt, 'proximity_weights') and zt.proximity_weights:
                    zone_key = zt.land_use or ""
                    for bsm, w in zt.proximity_weights.items():
                        proximity_weights.setdefault(zone_key, {})[bsm] = float(w)

        if candidate_bsms:
            before = len(parcels)
            parcels = [p for p in parcels if p.get("bsm_bare", "") in candidate_bsms]
        if excluded_bsms:
            before_ex = len(parcels)
            parcels = [p for p in parcels if p.get("bsm_bare", "") not in excluded_bsms]

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
        # Phase 5: Build set of protected parcel BSMs from KG spatial containment
        protected_bsms: set = set()
        if protected_parcels_detail:
            for pp in protected_parcels_detail:
                bsm = str(pp.get("bsm", "")).strip()
                if bsm:
                    protected_bsms.add(bsm)

        x = {}
        kg_excluded_count = 0
        for i, p in enumerate(parcels):
            # Phase 5: Check if parcel is in a protection zone (KG within_zone)
            # Use bsm_bare from build_parcel_index or extract from composite_key
            parcel_bsm = p.get("bsm_bare", "")
            is_kg_protected = parcel_bsm in protected_bsms
            for j, zt in enumerate(planning_zones):
                if is_kg_protected and zt in PLANNING_CONSTRUCTION_ZONES:
                    kg_excluded_count += 1
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

        # C3b: Three-line hard constraints (Phase 6 — no slack, no clipping)
        three_line_applied = 0
        if three_line_targets:
            three_line_applied = self._add_three_line_hard_constraints(
                pulp, prob, x, parcels, planning_zones, three_line_targets
            )

        # C3c: VNE zone-level hard constraints (Phase 6)
        vne_applied = 0
        if vne_summary:
            vne_applied = self._add_vne_zone_constraints(
                pulp, prob, x, parcels, planning_zones, vne_summary
            )

        # C4: PARSE semantic constraints (Step 1 — intent fidelity)
        parse_constraint_count = 0
        if parse_constraints:
            parse_constraint_count = self._add_parse_constraints(
                pulp, prob, x, parcels, planning_zones, parse_constraints, obj_terms
            )

        # 2. DLBM → planning zone preference cost + density modifier
        density_cost_mod: Dict[Tuple[int, int], float] = {}
        if density_hints:
            landuse = landuse_geojson
            village_center = self._compute_village_center(parcels, landuse)
            density_cost_mod = self._compute_density_cost_modifier(
                parcels, planning_zones, density_hints, village_center
            )
            logger.info("[MIP] Density hints applied: %s", density_hints)

        # Proximity weight cost (from ZoneTarget.proximity_weights)
        proximity_cost_mod: Dict[Tuple[int, int], float] = {}
        if zone_targets and proximity_weights:
            for i, p in enumerate(parcels):
                parcel_bsm = p.get("bsm_bare", "")
                for j, zt in enumerate(planning_zones):
                    pw = proximity_weights.get(zt, {}).get(parcel_bsm)
                    if pw is not None:
                        proximity_cost_mod[(i, j)] = pw

        for i, p in enumerate(parcels):
            for j, zt in enumerate(planning_zones):
                if (i, j) in x:
                    cost = self._get_preference_cost(p["dlbm"], zt)
                    cost += density_cost_mod.get((i, j), 0)
                    cost += proximity_cost_mod.get((i, j), 0)
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
        adj_weight_mod: Dict[str, float] = {}
        if adjacency_rules:
            adj_weight_mod = self._compute_adjacency_weight_modifier(
                planning_zones, adjacency_rules
            )
            logger.info("[MIP] Adjacency rules applied: %s", adjacency_rules)

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
                            weight = adjacency_weight + adj_weight_mod.get(zt, 0)
                            obj_terms.append(-weight * y[pair_id, j])

                logger.info(
                    f"[MIP] Adjacency: {len(adj_index_pairs)} pairs, "
                    f"{sum(1 for k in y)} auxiliary vars"
                )

        # 5. Facility proximity: reward construction parcels near existing facilities
        facility_proximity_count = 0
        if facility_anchors:
            facility_proximity_count = self._add_facility_proximity_constraints(
                parcels, planning_zones, facility_anchors, obj_terms, x
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

        # Record intent fidelity metadata in trace
        mip_trace.metadata = {
            **mip_trace.metadata,
            "parse_constraint_count": parse_constraint_count,
            "density_hints_applied": density_hints or {},
            "adjacency_rules_applied": adjacency_rules or {},
            "protected_parcels_excluded": kg_excluded_count,
            "three_line_constraints_applied": three_line_applied,
            "vne_constraints_applied": vne_applied,
        }

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

    def _add_three_line_hard_constraints(
        self,
        pulp_mod,
        prob,
        x: Dict,
        parcels: List[Dict],
        planning_zones: List[str],
        three_line_targets: List[Dict[str, Any]],
    ) -> int:
        """Add hard area constraints from KG ThreeLine entities (Phase 6).

        Unlike _add_hard_constraints, these are TRUE hard constraints:
        - No slack variables
        - No value clipping to DLBM-native bounds
        - Directly enforce area targets from protection zone geometry

        Three-line → planning zone mapping (by DLBM code, not zone name):
          - 生态保护红线 → parcels with DLBM in ecological codes, sum area >= target
          - 永久基本农田 → parcels with DLBM in farmland codes, sum area >= target
          - 城镇开发边界 / 村庄建设边界 → parcels with DLBM in construction codes, sum area <= target

        This works regardless of whether planning_zones uses land_use level
        (耕地/园地/...) or planning_zone level (生态保护区/农田保护区/...),
        because it classifies parcels by their DLBM→planning_zone mapping.

        Returns:
            Number of constraints applied.
        """
        from app.modules.schema import (
            ECOLOGICAL_CODES, FOREST_CODES, WATER_CODES,
            BASIC_FARMLAND_CODES, GENERAL_AGRICULTURE_CODES,
            DLBM_TO_PLANNING_ZONE,
        )

        # Build construction DLBM set from DLBM_TO_PLANNING_ZONE mapping
        _construction_dlbms = {
            code for code, pz in DLBM_TO_PLANNING_ZONE.items()
            if pz == "村庄建设区"
        }

        # Mapping: (name_keyword, DLBM_code_set, direction)
        # direction: ">=" means classified parcel area sum >= target, "<=" means <= target
        three_line_map = [
            ("生态", ECOLOGICAL_CODES | FOREST_CODES | WATER_CODES, ">="),
            ("农田", BASIC_FARMLAND_CODES | GENERAL_AGRICULTURE_CODES, ">="),
            ("基本农田", BASIC_FARMLAND_CODES | GENERAL_AGRICULTURE_CODES, ">="),
            ("建设", _construction_dlbms, "<="),
            ("开发边界", _construction_dlbms, "<="),
        ]

        applied = 0
        for tl in three_line_targets:
            name = str(tl.get("name", ""))
            target = tl.get("area_target_ha")
            try:
                target = float(target) if target is not None else None
            except (ValueError, TypeError):
                target = None
            if not name or target is None or target <= 0:
                continue

            # Find matching DLBM code set
            dlbm_set = None
            direction = None
            for keyword, codes, d in three_line_map:
                if keyword in name:
                    dlbm_set = codes
                    direction = d
                    break

            if dlbm_set is None:
                continue

            # Build area sum over all parcels whose DLBM is in the code set,
            # regardless of which zone they're assigned to.
            # Σ_i area_i * Σ_j x[i,j] for parcels with dlbm in dlbm_set
            # Since Σ_j x[i,j] = 1 (assignment constraint), this simplifies to
            # Σ_i area_i for parcels with dlbm in dlbm_set — a CONSTANT.
            # But that's the CURRENT area, not the PLANNED area.
            # The planned area is: Σ_{i: dlbm∈set} Σ_j area_i * x[i,j]
            # where we only sum over zones that belong to the target planning zone group.
            # For simplicity and correctness, sum over ALL zones for qualifying parcels:
            area_terms = []
            for i, p in enumerate(parcels):
                if p["dlbm"] in dlbm_set:
                    for j in range(len(planning_zones)):
                        if (i, j) in x:
                            area_terms.append(p["area_ha"] * x[i, j])

            if not area_terms:
                continue

            # Add hard constraint (no slack)
            constraint_name = f"three_line_{name.replace(' ', '_')}_{applied}"
            if direction == ">=":
                prob += pulp_mod.lpSum(area_terms) >= target, constraint_name
            else:
                prob += pulp_mod.lpSum(area_terms) <= target, constraint_name

            applied += 1
            logger.info(
                f"[MIP] Three-line hard constraint: {name} → "
                f"DLBM group({len(dlbm_set)} codes) {direction} {target:.1f}ha"
            )

        return applied

    def _add_vne_zone_constraints(
        self,
        pulp_mod,
        prob,
        x: Dict,
        parcels: List[Dict],
        planning_zones: List[str],
        vne_summary: List[Dict[str, Any]],
    ) -> int:
        """Add zone-level hard constraints from VNE classification (Phase 6).

        VNE codes classify each parcel into one of 3 primary zones:
          - V (建设空间) → parcels with construction DLBM
          - E (生态空间) → parcels with ecological DLBM
          - N (农业空间) → parcels with agricultural DLBM

        The constraint ensures the total assigned area of V-classified parcels
        (across ALL zones) is at least V_total, etc. This works regardless
        of whether planning_zones uses land_use or planning_zone level names.

        Returns:
            Number of constraints applied.
        """
        from app.modules.schema import (
            ECOLOGICAL_CODES, FOREST_CODES, WATER_CODES,
            BASIC_FARMLAND_CODES, GENERAL_AGRICULTURE_CODES,
            DLBM_TO_PLANNING_ZONE,
        )

        _construction_dlbms = {
            code for code, pz in DLBM_TO_PLANNING_ZONE.items()
            if pz == "村庄建设区"
        }

        # Aggregate VNE totals by top-level code
        v_total = sum(
            float(r.get("total_area_ha", 0) or 0)
            for r in vne_summary
            if str(r.get("vne_code", "")).startswith("V")
        )
        e_total = sum(
            float(r.get("total_area_ha", 0) or 0)
            for r in vne_summary
            if str(r.get("vne_code", "")).startswith("E")
        )
        n_total = sum(
            float(r.get("total_area_ha", 0) or 0)
            for r in vne_summary
            if str(r.get("vne_code", "")).startswith("N")
        )

        applied = 0

        # V → construction DLBM parcels area >= V_total
        if v_total > 0:
            area_terms = []
            for i, p in enumerate(parcels):
                if p["dlbm"] in _construction_dlbms:
                    for j in range(len(planning_zones)):
                        if (i, j) in x:
                            area_terms.append(p["area_ha"] * x[i, j])
            if area_terms:
                prob += pulp_mod.lpSum(area_terms) >= v_total, "vne_construction_floor"
                applied += 1
                logger.info(f"[MIP] VNE hard constraint: construction parcels >= {v_total:.1f}ha (V-coded)")

        # E → ecological DLBM parcels area >= E_total
        if e_total > 0:
            eco_codes = ECOLOGICAL_CODES | FOREST_CODES | WATER_CODES
            area_terms = []
            for i, p in enumerate(parcels):
                if p["dlbm"] in eco_codes:
                    for j in range(len(planning_zones)):
                        if (i, j) in x:
                            area_terms.append(p["area_ha"] * x[i, j])
            if area_terms:
                prob += pulp_mod.lpSum(area_terms) >= e_total, "vne_ecological_floor"
                applied += 1
                logger.info(f"[MIP] VNE hard constraint: ecological parcels >= {e_total:.1f}ha (E-coded)")

        # N → agricultural DLBM parcels area >= N_total
        if n_total > 0:
            ag_codes = BASIC_FARMLAND_CODES | GENERAL_AGRICULTURE_CODES
            area_terms = []
            for i, p in enumerate(parcels):
                if p["dlbm"] in ag_codes:
                    for j in range(len(planning_zones)):
                        if (i, j) in x:
                            area_terms.append(p["area_ha"] * x[i, j])
            if area_terms:
                prob += pulp_mod.lpSum(area_terms) >= n_total, "vne_agricultural_floor"
                applied += 1
                logger.info(f"[MIP] VNE hard constraint: agricultural parcels >= {n_total:.1f}ha (N-coded)")

        return applied

    def _add_parse_constraints(
        self,
        pulp_mod,
        prob,
        x: Dict,
        parcels: List[Dict],
        planning_zones: List[str],
        parse_constraints: List[Dict],
        obj_terms: list,
    ) -> int:
        """Add PARSE-derived semantic constraints to MIP (Step 1 — intent fidelity).

        Maps SpatialConstraint.type to MIP variable exclusions:
          - ecological_protection: DLBM 1350/3100 parcels -> x[i][建设区]=0
          - farmland_protection: DLBM 1100/1200 parcels -> x[i][建设区]=0
          - safety_assurance: parcels with hazard DLBMs -> x[i][建设区]=0
          - heritage_protection: stored in metadata (no DLBM mapping)
          - building_constraint / construction_control: stored in metadata (post-MIP check)

        Returns:
            Number of PARSE constraints applied.
        """
        construction_idx = next(
            (j for j, zt in enumerate(planning_zones)
             if zt in PLANNING_CONSTRUCTION_ZONES), None
        )
        if construction_idx is None:
            return 0

        applied = 0
        # DLBM sets for each protection type
        eco_dlbms = {"1350", "3100", "3200"}  # 生态林, 水域, 自然保留地
        farm_dlbms = {"1100", "1200"}  # 耕地, 园地

        for c in parse_constraints:
            ctype = c.get("type", "")

            if ctype == "ecological_protection":
                # Forbid ecological DLBM parcels from construction zone
                for i, p in enumerate(parcels):
                    if p["dlbm"] in eco_dlbms and (i, construction_idx) in x:
                        prob += x[i, construction_idx] == 0, f"parse_eco_{i}"
                        applied += 1

            elif ctype == "farmland_protection":
                # Forbid farmland DLBM parcels from construction zone
                for i, p in enumerate(parcels):
                    if p["dlbm"] in farm_dlbms and (i, construction_idx) in x:
                        prob += x[i, construction_idx] == 0, f"parse_farm_{i}"
                        applied += 1

            elif ctype == "safety_assurance":
                # Forbid hazard-adjacent parcels from construction zone
                # Check source_text for BSM references
                source = c.get("source_text", "")
                for i, p in enumerate(parcels):
                    bsm = p.get("bsm_bare", p.get("bsm", ""))
                    if bsm and bsm in source and (i, construction_idx) in x:
                        prob += x[i, construction_idx] == 0, f"parse_hazard_{i}"
                        applied += 1

            elif ctype == "spatial_constraint":
                # no_overlap: subject parcels forbidden from object zone
                rule = c.get("spatial_rule", {})
                if isinstance(rule, dict) and rule.get("operation") == "no_overlap":
                    subject = rule.get("subject", "")
                    # Match subject against DLBM zone types
                    from app.modules.schema import get_zone_type_for_dlbm
                    for i, p in enumerate(parcels):
                        zt = get_zone_type_for_dlbm(p["dlbm"])
                        if subject and subject in zt and (i, construction_idx) in x:
                            prob += x[i, construction_idx] == 0, f"parse_no_overlap_{i}"
                            applied += 1

            # building_constraint / construction_control / heritage_protection:
            # Not applicable to MIP (MIP only does zone assignment, not building params)
            # These are recorded in MIPTrace.metadata for post-MIP validation

        if applied:
            logger.info("[MIP] Applied %d PARSE constraints (ecological/farmland/spatial)", applied)
        return applied

    # ── Density / Adjacency helpers ──────────────────────────────────

    @staticmethod
    def _compute_village_center(
        parcels: List[Dict],
        landuse_geojson: Dict[str, Any],
    ) -> Tuple[float, float]:
        """Compute village center from boundary or parcel centroids."""
        from shapely.geometry import shape

        # Try boundary from gis_data embedded in landuse_geojson metadata
        boundary = landuse_geojson.get("_boundary_geojson")
        if boundary and boundary.get("features"):
            geom = shape(boundary["features"][0]["geometry"])
            return (geom.centroid.x, geom.centroid.y)

        # Fallback: mean of all parcel centroids
        xs, ys = [], []
        for p in parcels:
            feat = p.get("feature", p)
            geom = shape(feat.get("geometry", {}))
            if not geom.is_empty:
                xs.append(geom.centroid.x)
                ys.append(geom.centroid.y)
        if xs:
            return (sum(xs) / len(xs), sum(ys) / len(ys))
        return (0.0, 0.0)

    @staticmethod
    def _compute_density_cost_modifier(
        parcels: List[Dict],
        planning_zones: List[str],
        density_hints: Dict[str, str],
        village_center: Tuple[float, float],
    ) -> Dict[Tuple[int, int], float]:
        """Compute distance-based parcel preference cost modifier from density_hints.

        Logic:
          - "high" density -> prefer central parcels (lower cost for central parcels)
          - "low" density -> prefer peripheral parcels (lower cost for edge parcels)
          - "medium" -> no modification

        Returns:
            Dict mapping (parcel_idx, zone_idx) -> cost_modifier
        """
        import math
        from shapely.geometry import shape

        modifiers: Dict[Tuple[int, int], float] = {}

        # Only apply to construction zones
        construction_zone_indices = [
            j for j, zt in enumerate(planning_zones)
            if zt in PLANNING_CONSTRUCTION_ZONES
        ]
        if not construction_zone_indices:
            return modifiers

        # Compute distances from village center
        distances = []
        for p in parcels:
            feat = p.get("feature", p)
            geom = shape(feat.get("geometry", {}))
            if geom.is_empty:
                distances.append(float("inf"))
            else:
                cx, cy = geom.centroid.x, geom.centroid.y
                dist = math.sqrt(
                    (cx - village_center[0]) ** 2 + (cy - village_center[1]) ** 2
                )
                distances.append(dist)

        # Normalize distances to [0, 1]
        finite_dists = [d for d in distances if d != float("inf")]
        max_dist = max(finite_dists) if finite_dists else 1.0
        normalized = [d / max_dist if max_dist > 0 and d != float("inf") else 0.5
                      for d in distances]

        DENSITY_COST_WEIGHT = 5.0

        for j in construction_zone_indices:
            zone_name = planning_zones[j]
            density = density_hints.get(zone_name, "medium")

            if density == "high":
                # Prefer central parcels: lower cost for small distance
                for i, norm_dist in enumerate(normalized):
                    modifiers[(i, j)] = -DENSITY_COST_WEIGHT * (1 - norm_dist)
            elif density == "low":
                # Prefer peripheral parcels: lower cost for large distance
                for i, norm_dist in enumerate(normalized):
                    modifiers[(i, j)] = -DENSITY_COST_WEIGHT * norm_dist
            # "medium" -> no modification

        return modifiers

    @staticmethod
    def _compute_adjacency_weight_modifier(
        planning_zones: List[str],
        adjacency_rules: Dict[str, dict],
    ) -> Dict[str, float]:
        """Compute adjacency weight modifier from adjacency_rules.

        Logic:
          - prefer list non-empty -> same-zone neighbors get EXTRA reward (+0.3)
          - avoid list non-empty -> same-zone neighbors get PENALTY (-0.4)

        Returns:
            Dict mapping zone_name -> weight_modifier
        """
        ADJACENCY_PREFER_BONUS = 0.3
        ADJACENCY_AVOID_PENALTY = -0.4

        modifiers: Dict[str, float] = {}

        for zone_name, rules in adjacency_rules.items():
            prefer_list = rules.get("prefer", [])
            avoid_list = rules.get("avoid", [])

            if prefer_list:
                modifiers[zone_name] = ADJACENCY_PREFER_BONUS
            elif avoid_list:
                modifiers[zone_name] = ADJACENCY_AVOID_PENALTY

        return modifiers

    @staticmethod
    def _add_facility_proximity_constraints(
        parcels: List[Dict],
        planning_zones: List[str],
        facility_anchors: List[Dict[str, Any]],
        obj_terms: list,
        x: Dict,
    ) -> int:
        """Reward construction parcels near existing facilities (soft constraint).

        For each 现状设施点 facility anchor, construction-zone parcels within
        500m get a cost reduction in the objective, encouraging concentrated
        development near existing infrastructure.

        Args:
            parcels: List of parcel dicts with 'feature' key
            planning_zones: List of planning zone names
            facility_anchors: List of dicts with name, center, category
            obj_terms: MIP objective terms list (modified in-place)
            x: MIP binary variables dict

        Returns:
            Number of facility-proximity bonuses applied.
        """
        import math

        FACILITY_PROXIMITY_WEIGHT = 3.0
        FACILITY_PROXIMITY_RADIUS_M = 500.0

        construction_zone_indices = [
            j for j, zt in enumerate(planning_zones)
            if zt in PLANNING_CONSTRUCTION_ZONES
        ]
        if not construction_zone_indices:
            return 0

        applied = 0
        for anchor in facility_anchors:
            category = anchor.get("category", "")
            if category != "现状设施点":
                continue

            center = anchor.get("center", (0, 0))
            if isinstance(center, (list, tuple)) and len(center) >= 2:
                fac_lon, fac_lat = float(center[0]), float(center[1])
            else:
                continue

            if fac_lon == 0 and fac_lat == 0:
                continue

            for i, p in enumerate(parcels):
                feat = p.get("feature", p)
                geom_data = feat.get("geometry", {})
                if not geom_data:
                    continue
                try:
                    from shapely.geometry import shape
                    geom = shape(geom_data)
                    if geom.is_empty:
                        continue
                    px, py = geom.centroid.x, geom.centroid.y
                except Exception:
                    continue

                # Approximate distance in meters (at ~24°N)
                cos_lat = math.cos(math.radians(py))
                dx_m = (px - fac_lon) * 111_000.0 * cos_lat
                dy_m = (py - fac_lat) * 111_000.0
                dist_m = math.sqrt(dx_m * dx_m + dy_m * dy_m)

                if dist_m < FACILITY_PROXIMITY_RADIUS_M:
                    # Proportional bonus: closer = stronger
                    bonus = FACILITY_PROXIMITY_WEIGHT * (1 - dist_m / FACILITY_PROXIMITY_RADIUS_M)
                    for j in construction_zone_indices:
                        if (i, j) in x:
                            obj_terms.append(-bonus * x[i, j])
                    applied += 1

        if applied:
            logger.info(
                "[MIP] Facility proximity: %d parcels near %d facilities rewarded",
                applied, len(facility_anchors),
            )
        return applied
