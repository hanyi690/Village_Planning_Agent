"""P1: spatial_factors computes farmland / ecological overlap (not just audit)."""

from __future__ import annotations

from types import SimpleNamespace

from shapely.geometry import box

from app.domain.suitability.spatial_factors import SpatialFactorIndex


def _feature(coords) -> SimpleNamespace:
    return SimpleNamespace(
        geometry={"type": "Polygon", "coordinates": [coords]}
    )


def _parcel(coords) -> SimpleNamespace:
    return SimpleNamespace(
        bsm="P1",
        geometry={"type": "Polygon", "coordinates": [coords]},
    )


def _context(farmland: list | None = None, ecological: list | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        workspace=SimpleNamespace(
            metadata=SimpleNamespace(crs="EPSG:4326"),
            lines={"roads_current": []},
            points={
                "facilities_current": [],
                "hazard_points": [],
            },
            polygons={
                "farmland_protection": farmland or [],
                "ecological_redline": ecological or [],
            },
        ),
        constraint_index=None,
    )


def _policy(**overrides) -> SimpleNamespace:
    values = {
        "hazard_min_distance_m": 100.0,
        "road_preferred_distance_m": 500.0,
        "facility_preferred_distance_m": 800.0,
        "overlap_fraction_threshold": 1e-6,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


# parcel: 0..10 x 0..10  (metric projected to EPSG:3857, still axis aligned)
_PARCEL_COORDS = [[0, 0], [0, 10], [10, 10], [10, 0], [0, 0]]


def test_farmland_overlap_excludes_candidate_with_stable_code() -> None:
    farmland = [_feature([[0, 0], [0, 5], [5, 5], [5, 0], [0, 0]])]
    index = SpatialFactorIndex(_context(farmland=farmland), _policy())

    result = index.evaluate(_parcel(_PARCEL_COORDS), materialization_role="site_footprint")

    assert result.hard_feasible is False
    assert result.materialization_role == "site_footprint"
    assert "FARMLAND_PROTECTION_OVERLAP" in result.exclusion_codes
    assert "bundle:farmland_protection" in result.evidence_refs


def test_ecological_overlap_excludes_candidate_with_stable_code() -> None:
    ecological = [_feature([[2, 2], [2, 6], [6, 6], [6, 2], [2, 2]])]
    index = SpatialFactorIndex(_context(ecological=ecological), _policy())

    result = index.evaluate(_parcel(_PARCEL_COORDS), materialization_role="site_footprint")

    assert result.hard_feasible is False
    assert "ECOLOGICAL_REDLINE_OVERLAP" in result.exclusion_codes
    assert "bundle:ecological_redline" in result.evidence_refs


def test_no_overlap_keeps_candidate_feasible() -> None:
    index = SpatialFactorIndex(_context(), _policy())

    result = index.evaluate(_parcel(_PARCEL_COORDS), materialization_role="site_footprint")

    assert result.hard_feasible is True
    assert result.exclusion_codes == ()


def test_clipped_candidate_is_evaluated_instead_of_full_source_parcel() -> None:
    farmland = [_feature([[0, 0], [0, 5], [5, 5], [5, 0], [0, 0]])]
    index = SpatialFactorIndex(_context(farmland=farmland), _policy())

    result = index.evaluate(
        _parcel(_PARCEL_COORDS),
        geometry=box(6, 1, 9, 9).wkt,
        materialization_role="site_footprint",
    )

    assert result.hard_feasible is True
    assert result.exclusion_codes == ()


def test_protection_overlay_overlap_is_recorded_but_not_hard_excluded() -> None:
    farmland = [_feature([[0, 0], [0, 5], [5, 5], [5, 0], [0, 0]])]
    index = SpatialFactorIndex(_context(farmland=farmland), _policy())

    result = index.evaluate(
        _parcel(_PARCEL_COORDS),
        materialization_role="protection_overlay",
    )

    assert result.hard_feasible is True
    assert result.exclusion_codes == ()
    assert result.materialization_role == "protection_overlay"
    assert result.policy_key == "materialization_role_policy_v1:protection_overlay"
    factor = next(
        item
        for item in result.hard_constraint_factors
        if item["factor_code"] == "FARMLAND_PROTECTION_OVERLAP"
    )
    assert factor["policy"] == "overlay_constraint"
    assert factor["triggered"] is True
    assert factor["hard_exclusion"] is False
    assert any(
        item.get("step") == "spatial_factor"
        and item.get("factor_code") == "FARMLAND_PROTECTION_OVERLAP"
        and item.get("policy") == "overlay_constraint"
        for item in result.evaluation_trace
    )


def test_missing_materialization_role_fails_closed() -> None:
    index = SpatialFactorIndex(_context(), _policy())

    result = index.evaluate(_parcel(_PARCEL_COORDS))

    assert result.hard_feasible is False
    assert result.materialization_role == "unknown"
    assert result.exclusion_codes == ("MATERIALIZATION_ROLE_POLICY_UNAVAILABLE",)
