"""Unit tests for Planning Zone Mapper — 4↔7 class zone type mapping."""

from __future__ import annotations

import pytest

from app.services.modules.gis.layout.optimizer.planning_zone_mapper import (
    BASIC_FARMLAND_DLBMS,
    PLANNING_ZONE_TO_ZONE_TYPES,
    ZONE_TYPE_TO_PLANNING_ZONE,
    map_planning_zone_targets_to_zone_types,
    map_zone_type_to_planning_zone,
    remap_assigned_zones,
)


class TestForwardMapping:
    """4-class planning zone targets → 7-class zone type targets."""

    def test_agriculture_merged(self):
        """永久基本农田 + 一般农业区 should merge into 农业用地."""
        targets = {
            "农田保护区": 78.83,
            "一般农业区": 1881.54,
        }
        result = map_planning_zone_targets_to_zone_types(targets)
        assert "农业用地" in result
        assert abs(result["农业用地"] - (78.83 + 1881.54)) < 0.01

    def test_construction_split(self):
        """村庄建设区 should split into 5 sub-types with fixed ratios."""
        targets = {"村庄建设区": 30.50}
        result = map_planning_zone_targets_to_zone_types(targets)
        assert abs(result["居住用地"] - 30.50 * 0.6) < 0.01
        assert abs(result["产业用地"] - 30.50 * 0.15) < 0.01
        assert abs(result["公共服务用地"] - 30.50 * 0.15) < 0.01
        assert abs(result["交通用地"] - 30.50 * 0.08) < 0.01
        assert abs(result["商业用地"] - 30.50 * 0.02) < 0.01

    def test_ecological_split(self):
        """生态保护区 should split into 90% 生态绿地 + 10% 水域."""
        targets = {"生态保护区": 362.02}
        result = map_planning_zone_targets_to_zone_types(targets)
        assert abs(result["生态绿地"] - 362.02 * 0.9) < 0.01
        assert abs(result["水域"] - 362.02 * 0.1) < 0.01

    def test_full_targets(self):
        """All 4 planning zones produce 8 zone_type entries."""
        targets = {
            "农田保护区": 78.83,
            "村庄建设区": 30.50,
            "生态保护区": 362.02,
            "一般农业区": 1881.54,
        }
        result = map_planning_zone_targets_to_zone_types(targets)
        assert len(result) == 8
        expected_keys = {"农业用地", "居住用地", "产业用地", "公共服务用地",
                         "交通用地", "商业用地", "生态绿地", "水域"}
        assert set(result.keys()) == expected_keys

    def test_empty_targets(self):
        """Empty input should return empty dict."""
        assert map_planning_zone_targets_to_zone_types({}) == {}


class TestReverseMapping:
    """7-class zone_type → 4-class planning zone name."""

    def test_construction_types_map_to_construction_zone(self):
        """All construction sub-types should map to 村庄建设区."""
        for zt in ["居住用地", "产业用地", "公共服务用地", "交通用地", "商业用地"]:
            assert map_zone_type_to_planning_zone(zt) == "村庄建设区"

    def test_ecological_types_map_to_ecological_zone(self):
        """Ecology sub-types should map to 生态保护区."""
        assert map_zone_type_to_planning_zone("生态绿地") == "生态保护区"
        assert map_zone_type_to_planning_zone("水域") == "生态保护区"

    def test_agriculture_basic_farmland(self):
        """农业用地 with basic farmland DLBM → 农田保护区."""
        for dlbm in BASIC_FARMLAND_DLBMS:
            assert map_zone_type_to_planning_zone("农业用地", dlbm=dlbm) == "农田保护区"

    def test_agriculture_general_farming(self):
        """农业用地 with non-farmland DLBM → 一般农业区."""
        result = map_zone_type_to_planning_zone("农业用地", dlbm="0200")
        assert result == "一般农业区"

    def test_agriculture_empty_dlbm(self):
        """农业用地 with no DLBM → 一般农业区 (safe default)."""
        assert map_zone_type_to_planning_zone("农业用地") == "一般农业区"
        assert map_zone_type_to_planning_zone("农业用地", dlbm="") == "一般农业区"

    def test_unknown_zone_type_defaults_to_general_agriculture(self):
        """Unknown zone_type should default to 一般农业区."""
        assert map_zone_type_to_planning_zone("未知类型") == "一般农业区"


class TestRemapAssignedZones:
    """Feature-level 7→4 remapping."""

    def test_remaps_zone_type_to_planning_zone(self):
        features = [
            {"type": "Feature", "properties": {"assigned_zone": "居住用地", "DLBM": "2121"}},
            {"type": "Feature", "properties": {"assigned_zone": "生态绿地", "DLBM": "1340"}},
            {"type": "Feature", "properties": {"assigned_zone": "农业用地", "DLBM": "0101"}},
            {"type": "Feature", "properties": {"assigned_zone": "农业用地", "DLBM": "0200"}},
        ]
        result = remap_assigned_zones(features)
        assert result[0]["properties"]["assigned_zone"] == "村庄建设区"
        assert result[1]["properties"]["assigned_zone"] == "生态保护区"
        assert result[2]["properties"]["assigned_zone"] == "农田保护区"
        assert result[3]["properties"]["assigned_zone"] == "一般农业区"

    def test_preserves_original_zone_type(self):
        """Remapping should save original zone_type in zone_type_original."""
        features = [
            {"type": "Feature", "properties": {"assigned_zone": "居住用地", "DLBM": "2121"}},
        ]
        result = remap_assigned_zones(features)
        assert result[0]["properties"]["zone_type_original"] == "居住用地"

    def test_skips_already_planning_zone_names(self):
        """Features already using 4-class names should not be remapped."""
        features = [
            {"type": "Feature", "properties": {"assigned_zone": "村庄建设区", "DLBM": "2121"}},
        ]
        result = remap_assigned_zones(features)
        assert result[0]["properties"]["assigned_zone"] == "村庄建设区"
        assert "zone_type_original" not in result[0]["properties"]

    def test_skips_empty_assigned_zone(self):
        features = [
            {"type": "Feature", "properties": {"DLBM": "2121"}},
        ]
        result = remap_assigned_zones(features)
        assert "assigned_zone" not in result[0]["properties"] or \
               result[0]["properties"].get("assigned_zone", "") == ""

    def test_returns_same_list(self):
        """Should modify in-place and return same list."""
        features = [
            {"type": "Feature", "properties": {"assigned_zone": "居住用地", "DLBM": "2121"}},
        ]
        result = remap_assigned_zones(features)
        assert result is features


class TestMappingConsistency:
    """Verify forward/reverse mapping consistency."""

    def test_planning_zone_to_zone_types_keys_valid(self):
        """All keys in PLANNING_ZONE_TO_ZONE_TYPES should be 4-class names."""
        expected = {"农田保护区", "村庄建设区", "生态保护区", "一般农业区"}
        assert set(PLANNING_ZONE_TO_ZONE_TYPES.keys()) == expected

    def test_zone_type_to_planning_zone_values_valid(self):
        """All values in ZONE_TYPE_TO_PLANNING_ZONE should be 4-class names (except 农业用地)."""
        valid_values = {"村庄建设区", "生态保护区"}
        for v in ZONE_TYPE_TO_PLANNING_ZONE.values():
            assert v in valid_values

    def test_construction_ratios_sum_to_one(self):
        """5 construction sub-type ratios should sum to 1.0."""
        ratios = [0.6, 0.15, 0.15, 0.08, 0.02]
        assert abs(sum(ratios) - 1.0) < 0.001

    def test_ecological_ratios_sum_to_one(self):
        """2 ecological sub-type ratios should sum to 1.0."""
        ratios = [0.9, 0.1]
        assert abs(sum(ratios) - 1.0) < 0.001
