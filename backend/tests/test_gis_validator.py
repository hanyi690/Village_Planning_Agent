"""Tests for LayoutValidator — 5 validation checks."""

import pytest
from app.services.modules.gis.layout.validator import (
    LayoutValidator, ValidationReport, CheckResult, Violation,
    REQUIRED_ZONE_TYPES, MIN_ZONE_AREA_HA,
)


def _make_planning_zone_config(features):
    """Helper: build a planning_zone layer config from feature list."""
    return {
        "layerType": "planning_zone",
        "data": {"type": "FeatureCollection", "features": features},
    }


_ZONE_OFFSETS = [
    ([[0, 0], [0, 1], [1, 1], [1, 0], [0, 0]]),       # zone 0
    ([[10, 10], [10, 11], [11, 11], [11, 10], [10, 10]]),  # zone 1
    ([[20, 20], [20, 21], [21, 21], [21, 20], [20, 20]]),  # zone 2
    ([[30, 30], [30, 31], [31, 31], [31, 30], [30, 30]]),  # zone 3
]


def _make_zone_feature(zone_type, area_ha, dlbm="", current_zone="", slot=0):
    """Helper: build a planning_zone feature with assigned_zone and area_ha.

    slot: picks non-overlapping coordinates from _ZONE_OFFSETS.
    """
    return {
        "type": "Feature",
        "properties": {
            "assigned_zone": zone_type,
            "zone_type": zone_type,
            "area_ha": area_ha,
            "DLBM": dlbm,
            "current_zone_type": current_zone,
        },
        "geometry": {
            "type": "Polygon",
            "coordinates": [_ZONE_OFFSETS[slot]],
        },
    }


def _complete_layout():
    """A layout with all 4 required zones and sufficient area, non-overlapping."""
    return [
        _make_planning_zone_config([
            _make_zone_feature("永久基本农田保护区", 80.0, "0110", slot=0),
            _make_zone_feature("村庄建设区", 30.0, "2122", slot=1),
            _make_zone_feature("生态保护区", 400.0, "1340", slot=2),
            _make_zone_feature("一般农地区", 1800.0, "0200", slot=3),
        ])
    ]


class TestAreaConstraints:
    def test_pass_when_within_bounds(self):
        constraints = [
            {"field": "construction_area", "operator": "<=", "value": 50},
            {"field": "farmland_min", "operator": ">=", "value": 50},
            {"field": "ecological_min", "operator": ">=", "value": 100},
        ]
        validator = LayoutValidator()
        report = validator.validate(_complete_layout(), constraints)
        area_check = next(c for c in report.checks if c.check_name == "area_constraints")
        assert area_check.passed

    def test_fail_when_construction_exceeds_limit(self):
        constraints = [
            {"field": "construction_area", "operator": "<=", "value": 20},
        ]
        layout = [
            _make_planning_zone_config([
                _make_zone_feature("村庄建设区", 30.0),
            ])
        ]
        validator = LayoutValidator()
        report = validator.validate(layout, constraints)
        area_check = next(c for c in report.checks if c.check_name == "area_constraints")
        assert not area_check.passed
        assert any("建设用地面积" in v.message for v in area_check.violations)

    def test_fail_when_farmland_below_minimum(self):
        constraints = [
            {"field": "farmland_min", "operator": ">=", "value": 100},
        ]
        layout = [
            _make_planning_zone_config([
                _make_zone_feature("永久基本农田保护区", 50.0),
            ])
        ]
        validator = LayoutValidator()
        report = validator.validate(layout, constraints)
        area_check = next(c for c in report.checks if c.check_name == "area_constraints")
        assert not area_check.passed
        assert any("基本农田面积" in v.message for v in area_check.violations)

    def test_pass_with_no_constraints(self):
        validator = LayoutValidator()
        report = validator.validate(_complete_layout(), [])
        area_check = next(c for c in report.checks if c.check_name == "area_constraints")
        assert area_check.passed


class TestZoneCompleteness:
    def test_pass_with_all_zones(self):
        validator = LayoutValidator()
        report = validator.validate(_complete_layout())
        check = next(c for c in report.checks if c.check_name == "zone_completeness")
        assert check.passed

    def test_fail_with_missing_zone(self):
        layout = [
            _make_planning_zone_config([
                _make_zone_feature("永久基本农田保护区", 80.0),
                _make_zone_feature("村庄建设区", 30.0),
                # Missing: 生态保护区, 一般农地区
            ])
        ]
        validator = LayoutValidator()
        report = validator.validate(layout)
        check = next(c for c in report.checks if c.check_name == "zone_completeness")
        assert not check.passed
        assert check.violation_count == 2

    def test_ignores_non_planning_zone_layers(self):
        layout = [
            {"layerType": "boundary", "data": {"type": "FeatureCollection", "features": []}},
            _make_planning_zone_config([
                _make_zone_feature("永久基本农田保护区", 80.0),
                _make_zone_feature("村庄建设区", 30.0),
                _make_zone_feature("生态保护区", 400.0),
                _make_zone_feature("一般农地区", 1800.0),
            ]),
        ]
        validator = LayoutValidator()
        report = validator.validate(layout)
        check = next(c for c in report.checks if c.check_name == "zone_completeness")
        assert check.passed


class TestProtectedParcels:
    def test_pass_when_no_violations(self):
        layout = [
            _make_planning_zone_config([
                _make_zone_feature("村庄建设区", 30.0, "2122", "建设用地"),
            ])
        ]
        validator = LayoutValidator()
        report = validator.validate(layout)
        check = next(c for c in report.checks if c.check_name == "protected_parcels")
        assert check.passed

    def test_fail_when_protected_dlbm_in_construction(self):
        layout = [
            _make_planning_zone_config([
                _make_zone_feature("村庄建设区", 30.0, "0110", "农业用地"),
            ])
        ]
        validator = LayoutValidator()
        report = validator.validate(layout)
        check = next(c for c in report.checks if c.check_name == "protected_parcels")
        assert not check.passed
        assert any("受保护地块" in v.message for v in check.violations)

    def test_pass_when_protected_dlbm_in_correct_zone(self):
        layout = [
            _make_planning_zone_config([
                _make_zone_feature("永久基本农田保护区", 80.0, "0110", "农业用地"),
            ])
        ]
        validator = LayoutValidator()
        report = validator.validate(layout)
        check = next(c for c in report.checks if c.check_name == "protected_parcels")
        assert check.passed


class TestMinZoneArea:
    def test_pass_when_above_threshold(self):
        validator = LayoutValidator()
        report = validator.validate(_complete_layout())
        check = next(c for c in report.checks if c.check_name == "min_zone_area")
        assert check.passed

    def test_warning_when_below_threshold(self):
        layout = [
            _make_planning_zone_config([
                _make_zone_feature("村庄建设区", 0.1),
            ])
        ]
        validator = LayoutValidator()
        report = validator.validate(layout)
        check = next(c for c in report.checks if c.check_name == "min_zone_area")
        assert not check.passed
        assert all(v.severity == "warning" for v in check.violations)

    def test_no_warning_when_zone_absent(self):
        layout = [
            _make_planning_zone_config([
                _make_zone_feature("村庄建设区", 30.0),
            ])
        ]
        validator = LayoutValidator()
        report = validator.validate(layout)
        check = next(c for c in report.checks if c.check_name == "min_zone_area")
        # Missing zones have area=0, which is skipped (only warns if 0 < area < min)
        assert check.passed


class TestValidationReport:
    def test_pass_status(self):
        validator = LayoutValidator()
        report = validator.validate(_complete_layout())
        assert report.status == "pass"

    def test_fail_status_with_errors(self):
        layout = [
            _make_planning_zone_config([
                _make_zone_feature("村庄建设区", 30.0, "0110", "农业用地"),
            ])
        ]
        validator = LayoutValidator()
        report = validator.validate(layout)
        assert report.status == "fail"

    def test_total_violations_count(self):
        layout = [
            _make_planning_zone_config([
                _make_zone_feature("村庄建设区", 0.1, "0110", "农业用地"),
            ])
        ]
        validator = LayoutValidator()
        report = validator.validate(layout)
        assert report.total_violations > 0
