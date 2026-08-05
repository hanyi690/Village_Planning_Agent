"""Maximal covering location problem (MCLP) solver.

Pure module (``math`` / ``dataclasses`` / ``typing`` + optional ``pulp``).
Given a set of candidate facility sites and weighted demand points, choose up to
``n_facilities`` sites so that the total weighted demand covered within a
great-circle service radius is maximised.

Functions
---------
compute_coverage_matrix
    Boolean demand x candidate coverage matrix (haversine distance <= radius).
solve_maximal_covering
    Exact MIP formulation with ``pulp`` (falls back to greedy when unavailable).
greedy_maximal_covering
    Deterministic greedy fallback: repeatedly pick the candidate covering the
    most remaining weighted demand.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Sequence

_EARTH_RADIUS_M = 6371000.0


@dataclass
class DemandPoint:
    id: str
    lon: float
    lat: float
    weight: float = 1.0


@dataclass
class FacilityCandidate:
    candidate_id: str
    lon: float
    lat: float


def haversine_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """Great-circle distance in metres between two lon/lat points."""
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lam = math.radians(lon2 - lon1)
    a = (
        math.sin(d_phi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lam / 2.0) ** 2
    )
    return _EARTH_RADIUS_M * 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))


def compute_coverage_matrix(
    candidates: Sequence[FacilityCandidate],
    demand_points: Sequence[DemandPoint],
    service_radius_m: float,
) -> List[List[bool]]:
    """Return rows = demand points, cols = candidates boolean coverage matrix."""
    matrix = []
    for dp in demand_points:
        row = [
            haversine_m(dp.lon, dp.lat, c.lon, c.lat) <= service_radius_m
            for c in candidates
        ]
        matrix.append(row)
    return matrix


def greedy_maximal_covering(
    candidates: Sequence[FacilityCandidate],
    demand_points: Sequence[DemandPoint],
    service_radius_m: float,
    n_facilities: int = 1,
) -> List[str]:
    """Greedy fallback: pick candidate covering the most remaining demand."""
    if not candidates or not demand_points:
        return []
    cover = compute_coverage_matrix(candidates, demand_points, service_radius_m)
    remaining = [True] * len(demand_points)
    chosen: List[str] = []
    opened = 0
    while opened < n_facilities and any(remaining):
        best_idx = None
        best_gain = -1.0
        for j in range(len(candidates)):
            if candidates[j].candidate_id in chosen:
                continue
            gain = sum(
                demand_points[i].weight
                for i in range(len(demand_points))
                if remaining[i] and cover[i][j]
            )
            if gain > best_gain:
                best_gain = gain
                best_idx = j
        if best_idx is None or best_gain <= 0.0:
            break
        chosen.append(candidates[best_idx].candidate_id)
        opened += 1
        for i in range(len(demand_points)):
            if cover[i][best_idx]:
                remaining[i] = False
    return chosen


def solve_maximal_covering(
    candidates: Sequence[FacilityCandidate],
    demand_points: Sequence[DemandPoint],
    service_radius_m: float,
    n_facilities: int = 1,
) -> List[str]:
    """Solve MCLP exactly with pulp; fall back to greedy if pulp is missing."""
    if not candidates or not demand_points:
        return []
    try:
        import pulp
    except ImportError:
        return greedy_maximal_covering(
            candidates, demand_points, service_radius_m, n_facilities=n_facilities
        )
    cover = compute_coverage_matrix(candidates, demand_points, service_radius_m)
    n_d = len(demand_points)
    n_c = len(candidates)
    prob = pulp.LpProblem("maximal_covering", pulp.LpMaximize)
    x = [pulp.LpVariable(f"x_{j}", cat=pulp.LpBinary) for j in range(n_c)]
    y = [pulp.LpVariable(f"y_{i}", cat=pulp.LpBinary) for i in range(n_d)]
    prob += pulp.lpSum(demand_points[i].weight * y[i] for i in range(n_d))
    for i in range(n_d):
        prob += y[i] <= pulp.lpSum(cover[i][j] * x[j] for j in range(n_c))
    prob += pulp.lpSum(x) <= n_facilities
    prob.solve(pulp.PULP_CBC_CMD(msg=0))
    if pulp.LpStatus[prob.status] != "Optimal":
        return greedy_maximal_covering(
            candidates, demand_points, service_radius_m, n_facilities=n_facilities
        )
    chosen = [
        candidates[j].candidate_id
        for j in range(n_c)
        if x[j].value() is not None and x[j].value() > 0.5
    ]
    return chosen
