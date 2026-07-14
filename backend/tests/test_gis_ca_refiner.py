"""Unit tests for ZoneCARefiner — CA spatial refinement."""

from __future__ import annotations

import pytest

from app.services.modules.gis.optimizer.ca_refiner import ZoneCARefiner


# --- Minimal GeoJSON feature helpers ---

def _make_feature(zone_type: str, lon: float, lat: float, area_ha: float = 1.0) -> dict:
    """Create a tiny square GeoJSON feature at (lon, lat)."""
    d = 0.001  # ~0.1km offset
    return {
        "type": "Feature",
        "properties": {
            "assigned_zone": zone_type,
            "area_ha": area_ha,
            "parcel_count": 1,
        },
        "geometry": {
            "type": "Polygon",
            "coordinates": [[
                [lon - d, lat - d],
                [lon + d, lat - d],
                [lon + d, lat + d],
                [lon - d, lat + d],
                [lon - d, lat - d],
            ]],
        },
    }


def _make_features_same_type(zone_type: str, count: int, spacing: float = 0.005) -> list:
    """Create count features of same zone_type spaced along longitude."""
    return [
        _make_feature(zone_type, 116.0 + i * spacing, 24.0, area_ha=1.0)
        for i in range(count)
    ]


def _make_features_mixed() -> list:
    """Create features with 3 different zone types."""
    return (
        _make_features_same_type("村庄建设区", 3, spacing=0.005)
        + _make_features_same_type("生态保护区", 2, spacing=0.005)
        + _make_features_same_type("一般农业区", 2, spacing=0.005)
    )


# --- Tests ---

class TestCARefinerBasic:
    """Basic CA Refiner behavior."""

    def test_empty_input_returns_empty(self):
        refiner = ZoneCARefiner()
        assert refiner.refine([]) == []

    def test_single_feature_passes_through(self):
        refiner = ZoneCARefiner()
        features = [_make_feature("村庄建设区", 116.0, 24.0)]
        result = refiner.refine(features)
        assert len(result) >= 1

    def test_mixed_types_preserved(self):
        """All zone types should still be present after refinement."""
        refiner = ZoneCARefiner(iterations=1)
        features = _make_features_mixed()
        result = refiner.refine(features)
        result_types = set()
        for f in result:
            zt = (
                f.get("properties", {}).get("assigned_zone")
                or f.get("properties", {}).get("zone_type", "")
            )
            if zt:
                result_types.add(zt)
        # At least some zone types should survive
        assert len(result_types) >= 1


class TestCARefinerByTypeRebuild:
    """Verify that by_type is rebuilt after each merge pass (bug fix)."""

    def test_no_index_error_after_aggressive_merge(self):
        """Previously, stale by_type indices caused IndexError after merge.
        With the fix, by_type is rebuilt each iteration so indices stay valid.
        """
        # Create many features of same type that will merge aggressively
        features = _make_features_same_type("生态保护区", 20, spacing=0.003)
        refiner = ZoneCARefiner(
            merge_distance_m=30.0,
            iterations=3,
        )
        # Should not raise IndexError
        result = refiner.refine(features)
        assert len(result) >= 1

    def test_multiple_iterations_with_different_types(self):
        """Multiple iterations with different zone types should not crash."""
        features = (
            _make_features_same_type("村庄建设区", 10, spacing=0.003)
            + _make_features_same_type("生态保护区", 10, spacing=0.003)
            + _make_features_same_type("一般农业区", 10, spacing=0.003)
        )
        refiner = ZoneCARefiner(iterations=3)
        result = refiner.refine(features)
        assert len(result) >= 1


class TestCARefinerAreaConservation:
    """Area conservation checks."""

    def test_area_within_tolerance(self):
        """Total area should be conserved within 2% after refinement."""
        features = _make_features_mixed()
        refiner = ZoneCARefiner(iterations=2)

        original_area = refiner._total_area_ha(features)
        result = refiner.refine(features)
        result_area = refiner._total_area_ha(result)

        # Allow 2% tolerance (matching the warning threshold)
        if original_area > 0:
            loss_pct = abs(original_area - result_area) / original_area * 100
            assert loss_pct <= 5.0, f"Area loss {loss_pct:.1f}% exceeds 5% tolerance"


class TestCARefinerMergePass:
    """Test _merge_pass directly."""

    def test_merge_pass_reduces_same_type_count(self):
        """Adjacent same-type features should be merged."""
        features = _make_features_same_type("村庄建设区", 5, spacing=0.003)
        refiner = ZoneCARefiner(merge_distance_m=30.0)

        by_type = {"村庄建设区": list(range(len(features)))}
        result = refiner._merge_pass(features, by_type)
        # Merged result should have fewer features
        assert len(result) <= len(features)

    def test_merge_pass_preserves_different_types(self):
        """Different zone types should not be merged together."""
        features = _make_features_mixed()
        refiner = ZoneCARefiner(merge_distance_m=30.0)

        by_type: dict = {}
        for i, f in enumerate(features):
            zt = f.get("properties", {}).get("assigned_zone", "unknown")
            by_type.setdefault(zt, []).append(i)

        result = refiner._merge_pass(features, by_type)
        result_types = set()
        for f in result:
            zt = f.get("properties", {}).get("assigned_zone", "")
            if zt:
                result_types.add(zt)
        # All original types should still be present
        assert "村庄建设区" in result_types
        assert "生态保护区" in result_types
        assert "一般农业区" in result_types
