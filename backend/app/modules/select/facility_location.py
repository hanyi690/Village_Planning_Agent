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

from app.spatial.network.network_graph import NetworkGraphSnapshot

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
    *,
    network: NetworkGraphSnapshot | None = None,
    max_travel_time_min: float | None = None,
    allow_haversine_fallback: bool = False,
) -> List[List[bool]]:
    """Return a demand/candidate matrix using network time when configured."""
    matrix = []
    for dp in demand_points:
        row = []
        for c in candidates:
            if network is None:
                row.append(haversine_m(dp.lon, dp.lat, c.lon, c.lat) <= service_radius_m)
                continue
            route = network.route(
                {"type": "Point", "coordinates": [dp.lon, dp.lat]},
                {"type": "Point", "coordinates": [c.lon, c.lat]},
            )
            covered = bool(
                route.reachable
                and route.travel_time_min is not None
                and (max_travel_time_min is None or route.travel_time_min <= max_travel_time_min)
            )
            if not covered and allow_haversine_fallback:
                covered = haversine_m(dp.lon, dp.lat, c.lon, c.lat) <= service_radius_m
            row.append(covered)
        matrix.append(row)
    return matrix


def greedy_maximal_covering(
    candidates: Sequence[FacilityCandidate],
    demand_points: Sequence[DemandPoint],
    service_radius_m: float,
    n_facilities: int = 1,
    *,
    network: NetworkGraphSnapshot | None = None,
    max_travel_time_min: float | None = None,
    allow_haversine_fallback: bool = False,
) -> List[str]:
    """Greedy fallback: pick candidate covering the most remaining demand."""
    if not candidates or not demand_points:
        return []
    cover = compute_coverage_matrix(
        candidates,
        demand_points,
        service_radius_m,
        network=network,
        max_travel_time_min=max_travel_time_min,
        allow_haversine_fallback=allow_haversine_fallback,
    )
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
    *,
    network: NetworkGraphSnapshot | None = None,
    max_travel_time_min: float | None = None,
    allow_haversine_fallback: bool = False,
) -> List[str]:
    """Solve MCLP exactly with pulp; fall back to greedy if pulp is missing."""
    if not candidates or not demand_points:
        return []
    try:
        import pulp
    except ImportError:
        return greedy_maximal_covering(
            candidates,
            demand_points,
            service_radius_m,
            n_facilities=n_facilities,
            network=network,
            max_travel_time_min=max_travel_time_min,
            allow_haversine_fallback=allow_haversine_fallback,
        )
    cover = compute_coverage_matrix(
        candidates,
        demand_points,
        service_radius_m,
        network=network,
        max_travel_time_min=max_travel_time_min,
        allow_haversine_fallback=allow_haversine_fallback,
    )
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
            candidates,
            demand_points,
            service_radius_m,
            n_facilities=n_facilities,
            network=network,
            max_travel_time_min=max_travel_time_min,
            allow_haversine_fallback=allow_haversine_fallback,
        )
    chosen = [
        candidates[j].candidate_id
        for j in range(n_c)
        if x[j].value() is not None and x[j].value() > 0.5
    ]
    return chosen


def compute_network_coverage_matrix(
    candidates: Sequence[FacilityCandidate],
    demand_points: Sequence[DemandPoint],
    network: NetworkGraphSnapshot,
    *,
    max_travel_time_min: float,
) -> List[List[bool]]:
    """Network-only coverage matrix; disconnected points are never covered."""

    return compute_coverage_matrix(
        candidates,
        demand_points,
        service_radius_m=0.0,
        network=network,
        max_travel_time_min=max_travel_time_min,
        allow_haversine_fallback=False,
    )


def solve_network_maximal_covering(
    candidates: Sequence[FacilityCandidate],
    demand_points: Sequence[DemandPoint],
    network: NetworkGraphSnapshot,
    *,
    max_travel_time_min: float,
    n_facilities: int = 1,
) -> List[str]:
    """MCLP using routable travel time as the hard service impedance."""

    return solve_maximal_covering(
        candidates,
        demand_points,
        service_radius_m=0.0,
        n_facilities=n_facilities,
        network=network,
        max_travel_time_min=max_travel_time_min,
    )


__all__ = [
    "DemandPoint",
    "FacilityCandidate",
    "compute_coverage_matrix",
    "compute_network_coverage_matrix",
    "greedy_maximal_covering",
    "haversine_m",
    "solve_maximal_covering",
    "solve_network_maximal_covering",
]
