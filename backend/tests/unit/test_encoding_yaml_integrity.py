"""Unit tests for encoding YAML integrity (v3.0).

Verifies that encoding YAMLs do NOT contain derived fields (zone_type,
planning_zone, primary_zone) - these must live in mappings/ directory.
"""
import pytest
from pathlib import Path

from app.modules.schema.encodings.dicts.loader import get_center


class TestEncodingYamlNoDerivedFields:
    """Encoding YAMLs must not contain zone_type/planning_zone/primary_zone."""

    def _get_field_values(self, dict_name: str, field: str) -> list:
        """Return list of non-empty values for a field across all classes."""
        d = get_center().get(dict_name)
        values = []
        for entry in d.raw.get("classes", []):
            v = entry.get(field)
            if v:
                values.append(v)
        return values

    def test_appendix5_no_zone_type(self):
        vals = self._get_field_values("appendix5", "zone_type")
        assert vals == [], f"appendix5 should not have zone_type, found: {vals}"

    def test_ghflbm_no_zone_type(self):
        vals = self._get_field_values("ghflbm", "zone_type")
        assert vals == [], f"ghflbm should not have zone_type, found: {vals}"

    def test_vne_no_zone_type(self):
        vals = self._get_field_values("vne", "zone_type")
        assert vals == [], f"vne should not have zone_type, found: {vals}"

    def test_tugui_no_planning_zone(self):
        vals = self._get_field_values("tugui", "planning_zone")
        assert vals == [], f"tugui should not have planning_zone, found: {vals}"

    def test_tugui_no_primary_zone(self):
        vals = self._get_field_values("tugui", "primary_zone")
        assert vals == [], f"tugui should not have primary_zone, found: {vals}"

    def test_gbt21010_no_zone_type(self):
        """gbt21010 was already clean, verify it stays clean."""
        vals = self._get_field_values("gbt21010", "zone_type")
        assert vals == []


class TestNewEncodingsLoaded:
    """v3.0: 7 new encoding YAMLs load successfully."""

    def test_three_categories_loaded(self):
        d = get_center().get("three_categories")
        assert len(d.raw.get("classes", [])) == 3

    def test_zone_types_appendix5_loaded(self):
        d = get_center().get("zone_types_appendix5")
        assert len(d.raw.get("classes", [])) >= 5

    def test_zone_types_gbt50137_loaded(self):
        d = get_center().get("zone_types_gbt50137")
        assert len(d.raw.get("classes", [])) == 9

    def test_zone_types_town_loaded(self):
        d = get_center().get("zone_types_town")
        assert len(d.raw.get("classes", [])) == 9

    def test_zone_types_village_loaded(self):
        d = get_center().get("zone_types_village")
        assert len(d.raw.get("classes", [])) == 3

    def test_planning_zones_loaded(self):
        d = get_center().get("planning_zones")
        assert len(d.raw.get("classes", [])) == 6

    def test_primary_zones_loaded(self):
        d = get_center().get("primary_zones")
        classes = d.raw.get("classes", [])
        assert len(classes) == 3
        codes = [c.get("code") for c in classes]
        # v3.0 校正: 城镇空间 (not 建设空间)
        assert "城镇空间" in codes
        assert "建设空间" not in codes


class TestNewMappingsLoaded:
    """v3.0: New mapping YAMLs load successfully."""

    def test_dlbm_to_three_categories_loaded(self):
        m = get_center().get_mapping("gbt21010_to_three_categories")
        assert len(m.raw.get("mappings", [])) > 50

    def test_dlbm_to_zone_types_appendix5_loaded(self):
        m = get_center().get_mapping("gbt21010_to_zone_types_appendix5")
        assert len(m.raw.get("mappings", [])) > 50

    def test_dlbm_to_planning_zones_loaded(self):
        m = get_center().get_mapping("gbt21010_to_planning_zones")
        assert len(m.raw.get("mappings", [])) > 50

    def test_dlbm_to_primary_zones_loaded(self):
        m = get_center().get_mapping("gbt21010_to_primary_zones")
        assert len(m.raw.get("mappings", [])) > 50

    def test_planning_zones_to_primary_zones_loaded(self):
        m = get_center().get_mapping("planning_zones_to_primary_zones")
        assert len(m.raw.get("mappings", [])) == 6

    def test_planning_zones_to_control_code_loaded(self):
        m = get_center().get_mapping("planning_zones_to_control_code")
        assert len(m.raw.get("mappings", [])) == 6

    def test_appendix5_to_zone_types_appendix5_loaded(self):
        m = get_center().get_mapping("appendix5_to_zone_types_appendix5")
        assert len(m.raw.get("mappings", [])) >= 20

    def test_vne_to_zone_types_appendix5_loaded(self):
        m = get_center().get_mapping("vne_to_zone_types_appendix5")
        assert len(m.raw.get("mappings", [])) >= 20

    def test_vne_to_three_categories_loaded(self):
        m = get_center().get_mapping("vne_to_three_categories")
        assert len(m.raw.get("mappings", [])) >= 20

    def test_ghflbm_to_zone_types_appendix5_loaded(self):
        m = get_center().get_mapping("ghflbm_to_zone_types_appendix5")
        assert len(m.raw.get("mappings", [])) >= 10


class TestPrimaryZoneCorrection:
    """v3.0 校正: 建设空间 -> 城镇空间."""

    def test_primary_zone_names_contains_townspace(self):
        from app.modules.schema.encodings.code_sets import PRIMARY_ZONE_NAMES
        assert "城镇空间" in PRIMARY_ZONE_NAMES

    def test_primary_zone_names_not_contains_construction_space(self):
        from app.modules.schema.encodings.code_sets import PRIMARY_ZONE_NAMES
        assert "建设空间" not in PRIMARY_ZONE_NAMES

    def test_planning_zone_to_primary_zone_village_construction(self):
        from app.modules.schema.encodings.code_sets import PLANNING_ZONE_TO_PRIMARY_ZONE
        assert PLANNING_ZONE_TO_PRIMARY_ZONE["村庄建设区"] == "城镇空间"
