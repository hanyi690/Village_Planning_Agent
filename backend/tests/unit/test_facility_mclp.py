"""Unit tests for facility_location.py (maximal covering location problem)."""

from __future__ import annotations

from app.modules.spatial_ops.selection.facility_location import (
    DemandPoint,
    FacilityCandidate,
    compute_coverage_matrix,
    greedy_maximal_covering,
    solve_maximal_covering,
)


def _covered_weight(chosen_ids, candidates, demand_points, radius_m):
    chosen = [c for c in candidates if c.candidate_id in set(chosen_ids)]
    cover = compute_coverage_matrix(chosen, demand_points, radius_m)
    return sum(
        dp.weight for i, dp in enumerate(demand_points) if any(cover[i])
    )


def _candidates():
    return [
        FacilityCandidate("A", 0.0, 0.0),
        FacilityCandidate("B", 0.008, 0.0),
        FacilityCandidate("C", 0.016, 0.0),
    ]


def _demand():
    return [
        DemandPoint("d0", 0.0, 0.0, 10.0),
        DemandPoint("d1", 0.004, 0.0, 7.0),
        DemandPoint("d2", 0.008, 0.0, 8.0),
        DemandPoint("d3", 0.012, 0.0, 6.0),
        DemandPoint("d4", 0.016, 0.0, 9.0),
    ]


def test_compute_coverage_matrix_exact():
    candidates = [
        FacilityCandidate("A", 0.0, 0.0),
        FacilityCandidate("B", 0.01, 0.0),
    ]
    demand = [
        DemandPoint("p0", 0.0, 0.0),
        DemandPoint("p1", 0.005, 0.0),
        DemandPoint("p2", 0.02, 0.0),
    ]
    matrix = compute_coverage_matrix(candidates, demand, 1000.0)
    assert matrix == [
        [True, False],
        [True, True],
        [False, False],
    ]


def test_solve_maximal_covering_single_facility():
    chosen = solve_maximal_covering(_candidates(), _demand(), 1000.0, n_facilities=1)
    assert chosen == ["B"]
    assert _covered_weight(chosen, _candidates(), _demand(), 1000.0) == 40.0


def test_solve_maximal_covering_two_facilities():
    chosen = solve_maximal_covering(_candidates(), _demand(), 1000.0, n_facilities=2)
    assert len(chosen) <= 2
    assert _covered_weight(chosen, _candidates(), _demand(), 1000.0) == 40.0


def test_greedy_maximal_covering_valid_and_bounded():
    chosen = greedy_maximal_covering(_candidates(), _demand(), 1000.0, n_facilities=2)
    assert chosen
    assert len(chosen) <= 2
    assert _covered_weight(chosen, _candidates(), _demand(), 1000.0) == 40.0


def test_greedy_maximal_covering_single():
    chosen = greedy_maximal_covering(_candidates(), _demand(), 1000.0, n_facilities=1)
    assert chosen == ["B"]


def test_solve_no_candidates_returns_empty():
    demand = [DemandPoint("d", 0.0, 0.0)]
    assert solve_maximal_covering([], demand, 1000.0) == []
    assert greedy_maximal_covering([], demand, 1000.0) == []
