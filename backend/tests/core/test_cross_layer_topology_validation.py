from app.contracts.spatial.planned_state_contracts import PlannedAxis, PlannedFacility, PlannedState, PlannedZone
from app.domain.validation.validate_checks import check_cross_layer_topology


def test_cross_layer_topology_checks_road_axis_facility_and_area_layers() -> None:
    state = PlannedState(
        scenario_id="scenario:test",
        zones=[PlannedZone(zone_id="zone:1", geometry="POLYGON ((0 0, 10 0, 10 10, 0 10, 0 0))")],
        facilities=[PlannedFacility(feature_id="facility:1", geometry="POINT (100 100)")],
        axes=[PlannedAxis(feature_id="axis:1", geometry="LINESTRING (100 100, 110 100)")],
    )
    checks = check_cross_layer_topology(state)
    assert checks
    assert not all(item.passed for item in checks)
    assert any("cross_layer" in item.check_id for item in checks)
