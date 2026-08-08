"""P0-2: invalid WKT / missing geometry / constraint errors must fail, not skip."""
from app.agent.validate.checks import check_topology, check_hard_constraints, check_overlap
from app.modules.schema.contracts.planned_state_contracts import PlannedParcel, PlannedState


def _planned_with(geometry: str) -> PlannedState:
    return PlannedState(parcels=[PlannedParcel(bsm="P001", geometry=geometry)])


def test_topology_invalid_wkt_fails():
    checks = check_topology(_planned_with("NOT_WKT"))
    validity = next(c for c in checks if c.check_id == "topology_validity")
    assert validity.passed is False
    assert "P001" in (validity.actual_value or "") or "parse" in (validity.actual_value or "").lower()


def test_topology_empty_geometry_string_fails():
    checks = check_topology(_planned_with(""))
    validity = next(c for c in checks if c.check_id == "topology_validity")
    assert validity.passed is False


def test_overlap_invalid_wkt_fails():
    checks = check_overlap(_planned_with("NOT_WKT"))
    assert any(c.passed is False for c in checks)


def test_hard_constraints_query_exception_fails():
    class BoomIndex:
        def geometry_in_constraint(self, geojson):
            raise RuntimeError("index unavailable")

    planned = _planned_with("POLYGON ((0 0, 0 1, 1 1, 1 0, 0 0))")
    checks = check_hard_constraints(planned, BoomIndex())
    assert checks[0].passed is False
    assert "index unavailable" in (checks[0].actual_value or "") or "exception" in (checks[0].actual_value or "").lower()
