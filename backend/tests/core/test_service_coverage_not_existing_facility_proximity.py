from types import SimpleNamespace

from app.contracts.planning.scenario import ScenarioFeature
from app.domain.suitability.spatial_factors import SpatialFactorIndex


def test_existing_facility_proximity_is_not_service_coverage() -> None:
    context = SimpleNamespace(
        workspace=SimpleNamespace(
            metadata=SimpleNamespace(crs="EPSG:4326"),
            lines={"roads_current": []},
            points={
                "facilities_current": [
                    SimpleNamespace(geometry={"type": "Point", "coordinates": [0.0001, 0.0001]})
                ],
                "hazard_points": [],
            },
            polygons={"farmland_protection": [], "ecological_redline": []},
        ),
        constraint_index=None,
    )
    policy = SimpleNamespace(
        hazard_min_distance_m=100.0,
        road_preferred_distance_m=500.0,
        facility_preferred_distance_m=800.0,
        overlap_fraction_threshold=1e-6,
    )
    result = SpatialFactorIndex(context, policy).evaluate(
        SimpleNamespace(
            bsm="P1",
            geometry={
                "type": "Polygon",
                "coordinates": [[[0, 0], [0, 0.001], [0.001, 0.001], [0.001, 0], [0, 0]]],
            },
        )
    )

    assert "service_coverage" not in result.score_breakdown
    assert "existing_redundancy" in result.score_breakdown
    assert result.facility_coverage_score is None
