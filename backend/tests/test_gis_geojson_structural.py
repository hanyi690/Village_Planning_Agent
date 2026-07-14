"""Tests for GeoJSON RFC 7946 structural validation — P3 #9."""

import pytest
from app.services.modules.gis.validation.layout_validator import (
    LayoutValidator, CheckResult, Violation,
)


def _make_config(geojson: dict, layer_type: str = "planning_zone") -> dict:
    """Build a layer config with the given GeoJSON under 'data' key."""
    return {"layerType": layer_type, "data": geojson}


def _valid_feature_collection() -> dict:
    """A minimal valid GeoJSON FeatureCollection."""
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"zone_type": "居住用地"},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[0, 0], [0, 1], [1, 1], [1, 0], [0, 0]]],
                },
            }
        ],
    }


# ============================================
# TestGeoJSONStructuralValidation
# ============================================

class TestGeoJSONStructuralValidation:
    """Test _check_geojson_structural validates RFC 7946 compliance."""

    def test_valid_feature_collection_passes(self):
        validator = LayoutValidator()
        configs = [_make_config(_valid_feature_collection())]
        check = validator._check_geojson_structural(configs)
        assert check.passed, f"Valid GeoJSON should pass, violations: {check.violations}"

    def test_missing_type_fails(self):
        geojson = {"features": [{"type": "Feature", "properties": {}, "geometry": None}]}
        validator = LayoutValidator()
        check = validator._check_geojson_structural([_make_config(geojson)])
        assert not check.passed
        assert any("FeatureCollection" in v.message for v in check.violations)

    def test_wrong_type_fails(self):
        geojson = {"type": "Feature", "features": []}
        validator = LayoutValidator()
        check = validator._check_geojson_structural([_make_config(geojson)])
        assert not check.passed

    def test_missing_features_array_fails(self):
        geojson = {"type": "FeatureCollection", "features": "not_array"}
        validator = LayoutValidator()
        check = validator._check_geojson_structural([_make_config(geojson)])
        assert not check.passed

    def test_feature_missing_type_fails(self):
        geojson = {
            "type": "FeatureCollection",
            "features": [{"properties": {}, "geometry": None}],
        }
        validator = LayoutValidator()
        check = validator._check_geojson_structural([_make_config(geojson)])
        assert not check.passed
        assert any("Feature" in v.message for v in check.violations)

    def test_invalid_geometry_type_fails(self):
        geojson = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {},
                    "geometry": {"type": "Circle", "coordinates": [0, 0]},
                }
            ],
        }
        validator = LayoutValidator()
        check = validator._check_geojson_structural([_make_config(geojson)])
        assert not check.passed
        assert any("Circle" in v.message for v in check.violations)

    def test_out_of_bounds_longitude_fails(self):
        geojson = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {},
                    "geometry": {
                        "type": "Point",
                        "coordinates": [200, 24],  # lon=200 out of bounds
                    },
                }
            ],
        }
        validator = LayoutValidator()
        check = validator._check_geojson_structural([_make_config(geojson)])
        assert not check.passed
        assert any("经度" in v.message for v in check.violations)

    def test_out_of_bounds_latitude_fails(self):
        geojson = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {},
                    "geometry": {
                        "type": "Point",
                        "coordinates": [116, 100],  # lat=100 out of bounds
                    },
                }
            ],
        }
        validator = LayoutValidator()
        check = validator._check_geojson_structural([_make_config(geojson)])
        assert not check.passed
        assert any("纬度" in v.message for v in check.violations)

    def test_unclosed_polygon_ring_fails(self):
        geojson = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {},
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [[[0, 0], [0, 1], [1, 1], [1, 0]]],  # not closed
                    },
                }
            ],
        }
        validator = LayoutValidator()
        check = validator._check_geojson_structural([_make_config(geojson)])
        assert not check.passed
        assert any("未闭合" in v.message for v in check.violations)

    def test_closed_polygon_ring_passes(self):
        validator = LayoutValidator()
        configs = [_make_config(_valid_feature_collection())]
        check = validator._check_geojson_structural(configs)
        # The valid FC has a closed ring
        ring_violations = [v for v in check.violations if "未闭合" in v.message]
        assert len(ring_violations) == 0

    def test_crs_member_fails(self):
        geojson = _valid_feature_collection()
        geojson["crs"] = {"type": "name", "properties": {"name": "EPSG:4326"}}
        validator = LayoutValidator()
        check = validator._check_geojson_structural([_make_config(geojson)])
        assert not check.passed
        assert any("crs" in v.message for v in check.violations)

    def test_null_geometry_passes(self):
        geojson = {
            "type": "FeatureCollection",
            "features": [
                {"type": "Feature", "properties": {}, "geometry": None}
            ],
        }
        validator = LayoutValidator()
        check = validator._check_geojson_structural([_make_config(geojson)])
        assert check.passed

    def test_null_properties_passes(self):
        geojson = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": None,
                    "geometry": {"type": "Point", "coordinates": [116, 24]},
                }
            ],
        }
        validator = LayoutValidator()
        check = validator._check_geojson_structural([_make_config(geojson)])
        assert check.passed

    def test_valid_multi_polygon_passes(self):
        geojson = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {},
                    "geometry": {
                        "type": "MultiPolygon",
                        "coordinates": [
                            [[[0, 0], [0, 1], [1, 1], [1, 0], [0, 0]]],
                            [[[2, 2], [2, 3], [3, 3], [3, 2], [2, 2]]],
                        ],
                    },
                }
            ],
        }
        validator = LayoutValidator()
        check = validator._check_geojson_structural([_make_config(geojson)])
        assert check.passed

    def test_all_violations_are_warnings(self):
        """All GeoJSON structural violations should be warnings, not errors."""
        geojson = {"type": "Wrong", "features": "not_array", "crs": {}}
        validator = LayoutValidator()
        check = validator._check_geojson_structural([_make_config(geojson)])
        for v in check.violations:
            assert v.severity == "warning", f"Expected warning, got {v.severity}: {v.message}"

    def test_validates_both_data_and_geojson_keys(self):
        """Should validate GeoJSON under either 'data' or 'geojson' config key."""
        geojson = _valid_feature_collection()

        # With 'data' key
        config1 = {"layerType": "planning_zone", "data": geojson}
        validator = LayoutValidator()
        check1 = validator._check_geojson_structural([config1])

        # With 'geojson' key
        config2 = {"layerType": "planning_zone", "geojson": geojson}
        check2 = validator._check_geojson_structural([config2])

        assert check1.passed == check2.passed

    def test_empty_config_list_passes(self):
        validator = LayoutValidator()
        check = validator._check_geojson_structural([])
        assert check.passed

    def test_config_without_data_passes(self):
        """Config without data/geojson key should be skipped."""
        validator = LayoutValidator()
        check = validator._check_geojson_structural([{"layerType": "boundary"}])
        assert check.passed


# ============================================
# TestFlattenCoords
# ============================================

class TestFlattenCoords:
    """Test _flatten_coords helper method."""

    def test_flatten_point(self):
        flat = []
        LayoutValidator._flatten_coords([116.4, 24.3], flat)
        assert len(flat) == 1
        assert flat[0] == [116.4, 24.3]

    def test_flatten_line(self):
        flat = []
        LayoutValidator._flatten_coords([[116, 24], [117, 25]], flat)
        assert len(flat) == 2

    def test_flatten_polygon(self):
        flat = []
        LayoutValidator._flatten_coords([[[116, 24], [117, 25], [116, 24]]], flat)
        assert len(flat) == 3

    def test_flatten_multi_polygon(self):
        flat = []
        LayoutValidator._flatten_coords(
            [[[[0, 0], [0, 1], [1, 0], [0, 0]]], [[[2, 2], [2, 3], [3, 2], [2, 2]]]],
            flat,
        )
        assert len(flat) == 8  # 4 coords × 2 polygons


# ============================================
# TestRingClosure
# ============================================

class TestRingClosure:
    """Test polygon ring closure validation."""

    def test_closed_ring_no_violation(self):
        violations = []
        ring = [[0, 0], [0, 1], [1, 1], [1, 0], [0, 0]]
        LayoutValidator._check_ring(ring, violations, 0, 0)
        assert len(violations) == 0

    def test_unclosed_ring_produces_warning(self):
        violations = []
        ring = [[0, 0], [0, 1], [1, 1], [1, 0]]  # first != last
        LayoutValidator._check_ring(ring, violations, 0, 0)
        assert len(violations) == 1
        assert violations[0].severity == "warning"

    def test_tolerance_check(self):
        """Coordinates within 1e-10 tolerance should be considered closed."""
        violations = []
        # Slightly off but within tolerance
        ring = [[0, 0], [0, 1], [1, 1], [1, 0], [1e-11, 1e-11]]
        LayoutValidator._check_ring(ring, violations, 0, 0)
        assert len(violations) == 0, "Should be within tolerance"

    def test_ring_too_short_skipped(self):
        """Rings with <4 points should be skipped (degenerate)."""
        violations = []
        ring = [[0, 0], [1, 1]]  # only 2 points
        LayoutValidator._check_ring(ring, violations, 0, 0)
        assert len(violations) == 0
