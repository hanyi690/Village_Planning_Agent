"""PuLP zone allocator adapter: global MIP allocation (Wave O)."""

from types import SimpleNamespace

from app.agent.execute.zone_allocator_adapter import PuLPZoneAllocator, allocate_zones
from app.modules.ports.zone_allocator import ZoneAllocatorPort


def _parcel_sqm(area_sqm: float) -> SimpleNamespace:
    return SimpleNamespace(bsm="", area_ha=0.0, area_sqm=area_sqm)


def test_pulp_zone_allocator_implements_port():
    allocator = PuLPZoneAllocator()
    assert callable(allocator.allocate)
    assert callable(ZoneAllocatorPort.allocate)


def test_allocate_two_zones_within_targets():
    allocator = PuLPZoneAllocator()
    solution = allocator.allocate(
        targets={"Z1": 1.5, "Z2": 1.0},
        candidates={
            "Z1": [{"bsm": "P001", "area_ha": 1.0}, {"bsm": "P002", "area_ha": 1.0}],
            "Z2": [{"bsm": "P003", "area_ha": 0.5}, {"bsm": "P004", "area_ha": 0.5}],
        },
    )
    assert solution.feasible is True
    assert solution.assignments
    assigned_bsms = [entry.bsm for entry in solution.assignments]
    assert len(assigned_bsms) == len(set(assigned_bsms))

    area_by_zone: dict[str, float] = {}
    for entry in solution.assignments:
        area_by_zone[entry.zone_id] = area_by_zone.get(entry.zone_id, 0.0) + entry.area_ha
    for zone, area in area_by_zone.items():
        assert area <= {"Z1": 1.5, "Z2": 1.0}[zone] + 1e-6
    assert abs(solution.objective_value - 2.0) < 1e-6


def test_allocate_preserve_blacklist_not_assigned():
    solution = allocate_zones(
        targets={"Z1": 5.0},
        candidates={
            "Z1": [
                {"bsm": "P001", "area_ha": 1.0},
                {"bsm": "P002", "area_ha": 1.0},
                {"bsm": "P003", "area_ha": 1.0},
            ]
        },
        constraints=[{"type": "preserve", "bsms": ["P002"]}],
    )
    assert solution.feasible is True
    assigned = {entry.bsm for entry in solution.assignments}
    assert "P002" not in assigned
    assert "P002" in solution.unassigned_bsms


def test_allocate_area_from_parcel_by_bsm_lookup():
    solution = allocate_zones(
        targets={"Z1": 5.0},
        candidates={"Z1": ["P001", "P002"]},
        metadata={
            "parcel_by_bsm": {
                "P001": _parcel_sqm(12000),
                "P002": _parcel_sqm(14000),
            }
        },
    )
    assert solution.feasible is True
    assert {entry.bsm for entry in solution.assignments} == {"P001", "P002"}
    total = sum(entry.area_ha for entry in solution.assignments)
    assert abs(total - 2.6) < 1e-6


def test_allocate_no_inputs_infeasible():
    solution = allocate_zones(targets={}, candidates={})
    assert solution.feasible is False
    assert solution.assignments == []
    assert solution.diagnostics


def test_allocate_no_usable_candidates_infeasible():
    solution = allocate_zones(
        targets={"Z1": 1.0},
        candidates={"Z1": []},
    )
    assert solution.feasible is False
    assert solution.assignments == []
    assert any("No zone has usable candidate parcels" in item for item in solution.diagnostics)


def test_allocate_skips_zone_without_candidates():
    solution = allocate_zones(
        targets={"Z1": 1.0, "Z2": 1.0},
        candidates={
            "Z1": [{"bsm": "P001", "area_ha": 0.5}],
            "Z2": [],
        },
    )
    assert solution.feasible is True
    assert solution.assignments
    assert all(entry.zone_id == "Z1" for entry in solution.assignments)


def test_allocate_land_use_from_metadata():
    solution = allocate_zones(
        targets={"Z1": 1.0},
        candidates={"Z1": [{"bsm": "P001", "area_ha": 0.5}]},
        metadata={"Z1": {"land_use": "耕地"}},
    )
    assert solution.feasible is True
    assert solution.assignments[0].land_use == "耕地"
    assert solution.assignments[0].source == "allocator"
