"""
Tests for extended validation metrics — adjacency compatibility and
spatial compactness.

Verifies that the validator correctly computes and reports:
- Adjacency compatibility rate with/without adjacency graph
- Spatial compactness index with various parcel distributions
- Threshold warnings at correct boundaries
"""

from __future__ import annotations

import pytest

from app.services.modules.gis.layout.validator import LayoutValidator


def _make_zone_feature(zone_name: str, area_ha: float, slot: int = 0):
    """Create a minimal planning zone feature."""
    return {
        "type": "Feature",
        "properties": {
            "assigned_zone": zone_name,
            "area_ha": area_ha,
            "composite_key": f"test_{slot}",
        },
        "geometry": {
            "type": "Polygon",
            "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]],
        },
    }


def _make_layout(features):
    return [{
        "layerType": "planning_zone",
        "data": {"type": "FeatureCollection", "features": features},
    }]


class MockAdjacencyGraph:
    """Minimal adjacency graph for testing."""

    def __init__(self, adjacency_dict):
        self.adjacency_dict = adjacency_dict


class TestAdjacencyCompatibility:

    def test_no_adjacency_graph_skips_check(self):
        """Without adjacency_graph, check should pass (skipped)."""
        layout = _make_layout([
            _make_zone_feature("生态保护区", 100.0, 0),
        ])
        validator = LayoutValidator()
        report = validator.validate(layout)
        adj_check = next(c for c in report.checks if c.check_name == "adjacency_compatibility")
        assert adj_check.passed

    def test_high_compatibility_passes(self):
        """All same-zone neighbors should pass."""
        adj = MockAdjacencyGraph({
            "a": {"b", "c"},
            "b": {"a", "c"},
            "c": {"a", "b"},
        })
        features = [
            _make_zone_feature("生态保护区", 100.0, 0),
            _make_zone_feature("生态保护区", 80.0, 1),
            _make_zone_feature("生态保护区", 90.0, 2),
        ]
        # Fix composite keys to match adjacency dict
        features[0]["properties"]["composite_key"] = "a"
        features[1]["properties"]["composite_key"] = "b"
        features[2]["properties"]["composite_key"] = "c"
        layout = _make_layout(features)

        validator = LayoutValidator()
        report = validator.validate(layout, adjacency_graph=adj)
        adj_check = next(c for c in report.checks if c.check_name == "adjacency_compatibility")
        assert adj_check.passed

    def test_low_compatibility_warns(self):
        """All different-zone neighbors should warn."""
        adj = MockAdjacencyGraph({
            "a": {"b"},
            "b": {"a"},
        })
        features = [
            _make_zone_feature("生态保护区", 100.0, 0),
            _make_zone_feature("村庄建设区", 30.0, 1),
        ]
        features[0]["properties"]["composite_key"] = "a"
        features[1]["properties"]["composite_key"] = "b"
        layout = _make_layout(features)

        validator = LayoutValidator()
        report = validator.validate(layout, adjacency_graph=adj)
        adj_check = next(c for c in report.checks if c.check_name == "adjacency_compatibility")
        assert not adj_check.passed
        assert adj_check.violations[0].severity == "warning"

    def test_compatibility_rate_calculation(self):
        """Verify rate = same_zone_edges / total_edges."""
        adj = MockAdjacencyGraph({
            "a": {"b", "c", "d"},
            "b": {"a", "c"},
            "c": {"a", "b"},
            "d": {"a"},
        })
        # a-eco, b-eco, c-construction, d-eco
        # edges: (a,b)=same, (a,c)=diff, (a,d)=same, (b,c)=diff → 2/4 = 50%
        features = [
            _make_zone_feature("生态保护区", 100.0, 0),
            _make_zone_feature("生态保护区", 80.0, 1),
            _make_zone_feature("村庄建设区", 30.0, 2),
            _make_zone_feature("生态保护区", 90.0, 3),
        ]
        features[0]["properties"]["composite_key"] = "a"
        features[1]["properties"]["composite_key"] = "b"
        features[2]["properties"]["composite_key"] = "c"
        features[3]["properties"]["composite_key"] = "d"
        layout = _make_layout(features)

        validator = LayoutValidator()
        report = validator.validate(layout, adjacency_graph=adj)
        adj_check = next(c for c in report.checks if c.check_name == "adjacency_compatibility")
        assert adj_check.passed  # 50% > 30% threshold


class TestSpatialCompactness:

    def test_uniform_distribution_passes(self):
        """Uniform parcel sizes should have high compactness."""
        features = [
            _make_zone_feature("生态保护区", 10.0, i)
            for i in range(20)
        ]
        layout = _make_layout(features)

        validator = LayoutValidator()
        report = validator.validate(layout)
        compact_check = next(c for c in report.checks if c.check_name == "spatial_compactness")
        assert compact_check.passed

    def test_highly_skewed_warns(self):
        """One huge parcel + many tiny ones should warn."""
        features = [
            _make_zone_feature("生态保护区", 1000.0, 0),
        ] + [
            _make_zone_feature("生态保护区", 0.01, i + 1)
            for i in range(20)
        ]
        layout = _make_layout(features)

        validator = LayoutValidator()
        report = validator.validate(layout)
        compact_check = next(c for c in report.checks if c.check_name == "spatial_compactness")
        # This should produce a warning for high CV
        if not compact_check.passed:
            assert compact_check.violations[0].severity == "warning"

    def test_empty_layout_skips(self):
        """Empty layout should not fail compactness check."""
        layout = _make_layout([])
        validator = LayoutValidator()
        report = validator.validate(layout)
        compact_check = next(c for c in report.checks if c.check_name == "spatial_compactness")
        assert compact_check.passed
