from app.contracts.planning.relation_parameters import ServiceParameters
from app.contracts.planning.scenario import ScenarioFeature
from app.domain.demand.facility_demand_model import DemandPoint, DemandSnapshot
from app.spatial.network.network_graph import build_network_graph
from app.spatial.network.service_area import evaluate_facility_service


def _feature(feature_id: str, point: str) -> ScenarioFeature:
    return ScenarioFeature(
        feature_id=feature_id,
        scenario_id="scenario-1",
        target_id=feature_id,
        candidate_id=f"candidate:{feature_id}",
        geometry_kind="point",
        geometry_wkt=point,
        crs="EPSG:4326",
        generation_operation="test",
        source_refs=[f"candidate:{feature_id}"],
        relation_ids=[f"selection:{feature_id}:{feature_id}"],
    )


def test_network_service_is_capacity_limited() -> None:
    network = build_network_graph(
        [{"geometry": {"type": "LineString", "coordinates": [[0, 0], [0.01, 0]]}}],
        impedance="travel_time_min",
        network_ref="network:road:test",
        snap_tolerance_m=2,
    )
    demand = DemandSnapshot(
        demand_ref="demand:clinic",
        points=(
            DemandPoint(
                demand_id="settlement-1",
                geometry_wkt="POINT (0.01 0)",
                demand_value=100,
                facility_types=("clinic",),
            ),
        ),
    )
    measurement = evaluate_facility_service(
        _feature("clinic-1", "POINT (0 0)"),
        demand,
        network,
        ServiceParameters(
            demand_ref="demand:clinic",
            facility_type="clinic",
            max_travel_time_min=10,
            min_coverage_ratio=0.8,
            capacity=40,
            capacity_unit="person/day",
            network_ref="network:road:test",
        ),
    )

    assert measurement.status == "violated"
    assert measurement.coverage_ratio == 0.4
    assert measurement.covered_demand == 40
    assert measurement.capacity_used == 40


def test_service_filters_demand_by_facility_type() -> None:
    network = build_network_graph(
        [{"geometry": {"type": "LineString", "coordinates": [[0, 0], [0.01, 0]]}}],
        impedance="travel_time_min",
        network_ref="network:road:test",
    )
    demand = DemandSnapshot(
        demand_ref="demand:fire",
        points=(
            DemandPoint(
                demand_id="fire-1",
                geometry_wkt="POINT (0.01 0)",
                demand_value=20,
                facility_types=("fire_station",),
            ),
        ),
    )
    measurement = evaluate_facility_service(
        _feature("clinic-1", "POINT (0 0)"),
        demand,
        network,
        ServiceParameters(
            demand_ref="demand:fire",
            facility_type="clinic",
            max_travel_time_min=10,
            min_coverage_ratio=1,
            capacity=100,
            capacity_unit="person/day",
            network_ref="network:road:test",
        ),
    )

    assert measurement.status == "not_evaluable"
    assert measurement.covered_demand == 0
    assert measurement.demand_measurements[0].facility_type_match is False


def test_disconnected_matching_demand_is_zero_coverage() -> None:
    network = build_network_graph(
        [
            {"geometry": {"type": "LineString", "coordinates": [[0, 0], [0.01, 0]]}},
            {"geometry": {"type": "LineString", "coordinates": [[0.0101, 0], [0.02, 0]]}},
        ],
        impedance="travel_time_min",
        network_ref="network:road:test",
        snap_tolerance_m=1,
    )
    demand = DemandSnapshot(
        demand_ref="demand:clinic",
        points=(
            DemandPoint(
                demand_id="isolated",
                geometry_wkt="POINT (0.02 0)",
                demand_value=20,
                facility_types=("clinic",),
            ),
        ),
    )
    measurement = evaluate_facility_service(
        _feature("clinic-1", "POINT (0 0)"),
        demand,
        network,
        ServiceParameters(
            demand_ref="demand:clinic",
            facility_type="clinic",
            max_travel_time_min=20,
            min_coverage_ratio=0.8,
            capacity=100,
            capacity_unit="person/day",
            network_ref="network:road:test",
        ),
    )

    assert measurement.status == "not_reachable"
    assert measurement.coverage_ratio == 0.0
