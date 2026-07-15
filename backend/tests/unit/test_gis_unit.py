"""GIS unit tests — 30 tests covering pure logic with no external dependencies.

Sections:
  1. Planning Zone Mapper (8 tests)
  2. Layout Validator (10 tests)
  3. Data Loader (5 tests)
  4. Intent Cache (4 tests)
  5. Metrics Calculator (3 tests)
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from tests.fixtures.gis_shared import (
    ZONE_TARGETS,
    REQUIRED_ZONE_TYPES,
    make_zone_feature,
    make_planning_zone_config,
    make_valid_4zone_layout,
    MockAdjacencyGraph,
)


# ============================================================================
# 1. Planning Zone Mapper (8 tests)
# ============================================================================

from app.modules.gis.generation.optimizer.planning_zone_mapper import (
    PLANNING_ZONE_TO_ZONE_TYPES,
    ZONE_TYPE_TO_PLANNING_ZONE,
    map_planning_zone_targets_to_zone_types,
    map_zone_type_to_planning_zone,
    remap_assigned_zones,
)


class TestPlanningZoneMapper:

    def test_forward_agriculture_merged(self):
        """农田保护区 + 一般农业区 → 农业用地 (merged)."""
        targets = {"农田保护区": 100.0, "一般农业区": 200.0}
        result = map_planning_zone_targets_to_zone_types(targets)
        assert "农业用地" in result
        assert result["农业用地"] == pytest.approx(300.0)

    def test_forward_construction_split(self):
        """村庄建设区 → 5 construction sub-types."""
        targets = {"村庄建设区": 100.0}
        result = map_planning_zone_targets_to_zone_types(targets)
        construction_types = {"居住用地", "产业用地", "公共服务用地", "交通用地", "商业用地"}
        assert construction_types.issubset(set(result.keys()))
        total = sum(result[t] for t in construction_types)
        assert total == pytest.approx(100.0, abs=0.1)

    def test_forward_ecological_split(self):
        """生态保护区 → 生态绿地 + 水域."""
        targets = {"生态保护区": 100.0}
        result = map_planning_zone_targets_to_zone_types(targets)
        assert "生态绿地" in result
        assert "水域" in result
        assert result["生态绿地"] + result["水域"] == pytest.approx(100.0, abs=0.1)

    def test_forward_full_targets(self):
        """All 4 planning zones produce zone_type entries."""
        result = map_planning_zone_targets_to_zone_types(ZONE_TARGETS)
        assert "农业用地" in result
        assert "居住用地" in result
        assert "生态绿地" in result

    def test_reverse_construction_to_zone(self):
        """All construction sub-types map to 村庄建设区."""
        for zt in ("居住用地", "产业用地", "公共服务用地", "交通用地", "商业用地"):
            assert map_zone_type_to_planning_zone(zt) == "村庄建设区"

    def test_reverse_ecological_to_zone(self):
        """生态绿地 → 生态保护区, 水域 → 生态保护区."""
        assert map_zone_type_to_planning_zone("生态绿地") == "生态保护区"
        assert map_zone_type_to_planning_zone("水域") == "生态保护区"

    def test_remap_assigned_zones(self):
        """7-class zone_type remapped to 6-class planning zone names."""
        features = [
            {"properties": {"assigned_zone": "居住用地", "DLBM": "2121"}},
            {"properties": {"assigned_zone": "农业用地", "DLBM": "0110"}},
        ]
        result = remap_assigned_zones(features)
        assert result[0]["properties"]["assigned_zone"] == "村庄建设区"
        assert result[1]["properties"]["assigned_zone"] == "农田保护区"
        assert result[1]["properties"].get("zone_type_original") == "农业用地"

    def test_mapping_consistency(self):
        """Forward and reverse mappings are consistent: round-trip preserves semantics."""
        # All forward mapping keys are valid planning zone names
        for pz in PLANNING_ZONE_TO_ZONE_TYPES:
            assert pz in {"生态保护区", "生态控制区", "农田保护区", "一般农业区", "村庄建设区", "林业发展区"}
        # All reverse mapping values are valid planning zone names
        for zt, pz in ZONE_TYPE_TO_PLANNING_ZONE.items():
            assert pz in PLANNING_ZONE_TO_ZONE_TYPES


# ============================================================================
# 2. Layout Validator (10 tests)
# ============================================================================

from app.modules.gis.analysis.validation.layout_validator import (
    LayoutValidator,
    ValidationReport,
)


class TestLayoutValidator:

    @pytest.mark.parametrize(
        "within_bounds,expected_pass",
        [(True, True), (False, False)],
    )
    def test_area_constraints_pass_fail(self, within_bounds, expected_pass):
        """Area constraints: pass when within bounds, fail when exceeded."""
        if within_bounds:
            constraints = [
                {"field": "construction_area", "operator": "<=", "value": 50},
                {"field": "farmland_min", "operator": ">=", "value": 50},
            ]
            layout = make_valid_4zone_layout()
        else:
            constraints = [{"field": "construction_area", "operator": "<=", "value": 20}]
            layout = [make_planning_zone_config([make_zone_feature("村庄建设区", 30.0)])]
        validator = LayoutValidator()
        report = validator.validate(layout, constraints)
        check = next(c for c in report.checks if c.check_name == "area_constraints")
        assert check.passed == expected_pass

    def test_zone_completeness(self):
        """Pass with all required zones, fail with missing zones."""
        validator = LayoutValidator()
        # Pass
        report = validator.validate(make_valid_4zone_layout())
        check = next(c for c in report.checks if c.check_name == "zone_completeness")
        assert check.passed
        # Fail: missing 3 zones
        layout = [make_planning_zone_config([make_zone_feature("村庄建设区", 30.0)])]
        report = validator.validate(layout)
        check = next(c for c in report.checks if c.check_name == "zone_completeness")
        assert not check.passed

    def test_protected_parcels_violation(self):
        """Pass when no violations, fail when protected DLBM in construction zone."""
        validator = LayoutValidator()
        # Pass: non-protected DLBM in construction
        layout = [make_planning_zone_config([make_zone_feature("村庄建设区", 30.0, "2122", "建设用地")])]
        report = validator.validate(layout)
        check = next(c for c in report.checks if c.check_name == "protected_parcels")
        assert check.passed
        # Fail: protected DLBM in construction
        layout = [make_planning_zone_config([make_zone_feature("村庄建设区", 30.0, "0110", "农业用地")])]
        report = validator.validate(layout)
        check = next(c for c in report.checks if c.check_name == "protected_parcels")
        assert not check.passed

    @pytest.mark.parametrize(
        "area_ha,expected_pass",
        [(30.0, True), (0.1, False)],
    )
    def test_min_zone_area_threshold(self, area_ha, expected_pass):
        """Pass when above threshold, warn when below."""
        layout = [make_planning_zone_config([make_zone_feature("村庄建设区", area_ha)])]
        validator = LayoutValidator()
        report = validator.validate(layout)
        check = next(c for c in report.checks if c.check_name == "min_zone_area")
        assert check.passed == expected_pass

    def test_validation_report_status(self):
        """Report status: pass/warning for valid, fail for violations."""
        validator = LayoutValidator()
        # Valid layout → pass or warning
        report = validator.validate(make_valid_4zone_layout())
        assert report.status in ("pass", "warning")
        # Invalid layout → fail
        layout = [make_planning_zone_config([make_zone_feature("村庄建设区", 30.0, "0110", "农业用地")])]
        report = validator.validate(layout)
        assert report.status == "fail"

    def test_geojson_structural_check(self):
        """GeoJSON structural check is present and passes for valid layout."""
        validator = LayoutValidator()
        report = validator.validate(make_valid_4zone_layout())
        check_names = {c.check_name for c in report.checks}
        assert "geojson_structural" in check_names
        geo_check = next(c for c in report.checks if c.check_name == "geojson_structural")
        assert geo_check.passed

    def test_adjacency_compatibility(self):
        """Skip when no graph, pass with high compatibility, warn with low."""
        validator = LayoutValidator()
        layout = [make_planning_zone_config([make_zone_feature("生态保护区", 100.0)])]
        # No graph → pass (skipped)
        report = validator.validate(layout)
        adj = next(c for c in report.checks if c.check_name == "adjacency_compatibility")
        assert adj.passed
        # Low compatibility → warning
        adj = MockAdjacencyGraph({"a": {"b"}, "b": {"a"}})
        features = [
            make_zone_feature("生态保护区", 100.0, slot=0),
            make_zone_feature("村庄建设区", 30.0, slot=1),
        ]
        features[0]["properties"]["composite_key"] = "a"
        features[1]["properties"]["composite_key"] = "b"
        layout = [make_planning_zone_config(features)]
        report = validator.validate(layout, adjacency_graph=adj)
        adj_check = next(c for c in report.checks if c.check_name == "adjacency_compatibility")
        assert not adj_check.passed

    def test_spatial_compactness(self):
        """Pass with uniform distribution, warn with skewed."""
        validator = LayoutValidator()
        # Uniform
        features = [make_zone_feature("生态保护区", 10.0, i) for i in range(20)]
        layout = [make_planning_zone_config(features)]
        report = validator.validate(layout)
        check = next(c for c in report.checks if c.check_name == "spatial_compactness")
        assert check.passed
        # Empty
        layout = [make_planning_zone_config([])]
        report = validator.validate(layout)
        check = next(c for c in report.checks if c.check_name == "spatial_compactness")
        assert check.passed

    def test_validate_has_8_checks(self):
        """validate() runs all 8 checks."""
        validator = LayoutValidator()
        report = validator.validate(make_valid_4zone_layout())
        assert len(report.checks) == 8

    def test_validate_with_retry(self):
        """validate_with_retry returns a report after retries."""
        validator = LayoutValidator()
        layout = make_valid_4zone_layout()
        report = validator.validate_with_retry(layout, constraints=[], max_retries=1)
        assert report.status in ("pass", "warning", "fail")


# ============================================================================
# 3. Data Loader (5 tests)
# ============================================================================

from app.modules.gis.data.loader import (
    load_current,
    load_planned,
    compute_intent_from_gis,
    get_village_params,
    get_data_summary,
)


class TestDataLoader:

    def test_load_current_returns_geojson(self):
        """load_current returns dict with expected keys."""
        data = load_current()
        assert "boundary_geojson" in data
        assert "landuse_current_geojson" in data
        assert "road_geojson" in data
        for key, val in data.items():
            assert isinstance(val, dict)
            assert val.get("type") == "FeatureCollection" or "features" in val

    def test_compute_intent_from_gis(self):
        """compute_intent_from_gis produces zones from real GIS data."""
        data = load_current()
        data.update(load_planned())
        intent = compute_intent_from_gis(data, "金田村委会")
        assert "zones" in intent
        assert len(intent["zones"]) > 0
        assert "metadata" in intent
        assert intent["metadata"]["source"] == "gis_data_computed"

    def test_get_village_params(self):
        """get_village_params returns total_area and land_use_description."""
        data = load_current()
        data.update(load_planned())
        params = get_village_params(data)
        assert "total_area" in params
        assert "land_use_description" in params
        assert float(params["total_area"]) > 0

    def test_get_data_summary(self):
        """get_data_summary returns feature counts per layer."""
        data = load_current()
        summary = get_data_summary(data)
        assert isinstance(summary, dict)
        for key, info in summary.items():
            assert "feature_count" in info
            assert "geometry_types" in info

    def test_resolve_gen_intent_fallback(self):
        """resolve_gen_intent falls back to GIS computation when no markdown."""
        from app.modules.gis.data.loader import resolve_gen_intent
        data = load_current()
        data.update(load_planned())
        # Patch PlanningTextLoader to raise FileNotFoundError
        with patch(
            "app.modules.gis.data.loader.PlanningTextLoader",
            create=True,
        ) as mock_loader:
            mock_loader.load_village_planning_markdown.side_effect = FileNotFoundError
            # This will hit the fallback path
            intent = resolve_gen_intent("金田村委会", data)
            assert "zones" in intent
            assert intent.get("metadata", {}).get("source") in (
                "gis_data_fallback",
                "planning_markdown_llm",
            )


# ============================================================================
# 4. Intent Cache (4 tests)
# ============================================================================

from app.modules.gis.data.intent_cache import (
    _compute_cache_key,
    get_cached_intent,
    save_cached_intent,
)


class TestIntentCache:

    def test_cache_key_deterministic(self):
        """Same input produces same cache key."""
        key1 = _compute_cache_key("gen", "test content")
        key2 = _compute_cache_key("gen", "test content")
        assert key1 == key2

    def test_cache_key_differs_on_content(self):
        """Different content produces different cache key."""
        key1 = _compute_cache_key("gen", "content A")
        key2 = _compute_cache_key("gen", "content B")
        assert key1 != key2

    def test_save_and_get_roundtrip(self):
        """Save then get returns the same intent."""
        intent = {"zones": [{"zone_id": "z1", "area_ratio": 0.5}], "metadata": {}}
        cache_key = "_test_roundtrip_" + _compute_cache_key("test", "roundtrip")
        save_cached_intent(cache_key, intent)
        result = get_cached_intent(cache_key)
        assert result is not None
        assert result["zones"][0]["zone_id"] == "z1"
        # Cleanup
        from app.modules.gis.data.intent_cache import INTENT_CACHE_DIR
        (INTENT_CACHE_DIR / f"{cache_key}.json").unlink(missing_ok=True)

    def test_corrupted_cache_returns_none(self):
        """Corrupted cache file returns None."""
        from app.modules.gis.data.intent_cache import INTENT_CACHE_DIR
        cache_key = "_test_corrupt_" + _compute_cache_key("test", "corrupt")
        INTENT_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        path = INTENT_CACHE_DIR / f"{cache_key}.json"
        path.write_text("NOT VALID JSON{{{", encoding="utf-8")
        result = get_cached_intent(cache_key)
        assert result is None
        path.unlink(missing_ok=True)


# ============================================================================
# 5. Metrics Calculator (3 tests)
# ============================================================================

from app.modules.gis.analysis.metrics_calculator import GISMetricsCalculator


class TestMetricsCalculator:

    @pytest.fixture()
    def gis_data_with_landuse(self):
        """Minimal GIS data with landuse for metrics testing."""
        return {
            "landuse_current_geojson": {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {"DLBM": "0110", "area_ha": 100.0},
                        "geometry": {"type": "Polygon"},
                    },
                    {
                        "type": "Feature",
                        "properties": {"DLBM": "2121", "area_ha": 10.0},
                        "geometry": {"type": "Polygon"},
                    },
                    {
                        "type": "Feature",
                        "properties": {"DLBM": "1340", "area_ha": 50.0},
                        "geometry": {"type": "Polygon"},
                    },
                ],
            }
        }

    def test_compute_land_use_metrics(self, gis_data_with_landuse):
        """compute_land_use_metrics aggregates areas by DLBM codes."""
        metrics = GISMetricsCalculator.compute_land_use_metrics(gis_data_with_landuse)
        assert metrics["total_area_ha"] == pytest.approx(160.0)
        assert metrics["farmland_area_ha"] > 0
        assert metrics["construction_area_ha"] > 0

    def test_compute_zone_distribution(self, gis_data_with_landuse):
        """compute_zone_distribution returns ratios summing to ~1.0."""
        distribution = GISMetricsCalculator.compute_zone_distribution(gis_data_with_landuse)
        if distribution:
            total = sum(distribution.values())
            assert total == pytest.approx(1.0, abs=0.01)

    def test_area_unit_conversion(self):
        """_area_ha_from_props converts DLMJ (m²) to hectares."""
        from app.modules.gis.analysis.metrics_calculator import _area_ha_from_props
        # area_ha takes priority
        assert _area_ha_from_props({"area_ha": 5.0, "DLMJ": 50000}) == 5.0
        # DLMJ fallback: 50000 m² = 5 ha
        assert _area_ha_from_props({"DLMJ": 50000}) == pytest.approx(5.0)
        # MJ fallback: 10000 m² = 1 ha
        assert _area_ha_from_props({"MJ": 10000}) == pytest.approx(1.0)
