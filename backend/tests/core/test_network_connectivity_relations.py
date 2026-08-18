from app.contracts.planning.relation_parameters import ConnectParameters
from app.contracts.planning.scenario import ScenarioFeature
from app.domain.relations.network_evaluators import evaluate_connectivity
from app.spatial.network.network_graph import build_network_graph


def _point(feature_id: str, point: str) -> ScenarioFeature:
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
    )


def test_straight_line_close_but_disconnected_is_not_connected() -> None:
    network = build_network_graph(
        [
            {"geometry": {"type": "LineString", "coordinates": [[0, 0], [0.01, 0]]}},
            {"geometry": {"type": "LineString", "coordinates": [[0.0101, 0], [0.02, 0]]}},
        ],
        impedance="travel_time_min",
        network_ref="network:road:test",
        snap_tolerance_m=1,
    )
    result = evaluate_connectivity(
        _point("a", "POINT (0 0)"),
        _point("b", "POINT (0.02 0)"),
        network,
        ConnectParameters(
            network_kind="road",
            endpoint_tolerance_m=100,
            network_ref="network:road:test",
        ),
    )

    assert result.status == "not_reachable"
    assert result.connected is False
