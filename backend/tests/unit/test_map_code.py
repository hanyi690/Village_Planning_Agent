"""Unit tests for map_code tool (v3.0).

Tests cross-system mapping suggestions: input recognition + multi-target output.
"""
import pytest

from app.tools.gis.lookup import map_code


class TestMapCodeDlbmInput:
    """map_code with DLBM (gbt21010) code input."""

    def test_dlbm_returns_multiple_mappings(self):
        r = map_code.invoke({"code_or_name": "0101"})
        assert r["input"]["system"] == "gbt21010"
        assert r["input"]["name"] == "水田"
        mappings = r["mappings"]
        assert len(mappings) >= 3, f"Expected >=3 mappings, got {len(mappings)}"

    def test_dlbm_includes_three_categories(self):
        r = map_code.invoke({"code_or_name": "0101"})
        systems = [m["system"] for m in r["mappings"]]
        assert "three_categories" in systems
        cat = next(m for m in r["mappings"] if m["system"] == "three_categories")
        assert cat["code"] == "农用地"

    def test_dlbm_includes_zone_type(self):
        r = map_code.invoke({"code_or_name": "0101"})
        systems = [m["system"] for m in r["mappings"]]
        assert "zone_type_appendix5" in systems

    def test_dlbm_includes_planning_zone(self):
        r = map_code.invoke({"code_or_name": "0101"})
        systems = [m["system"] for m in r["mappings"]]
        assert "planning_zone" in systems

    def test_dlbm_includes_primary_zone(self):
        r = map_code.invoke({"code_or_name": "0101"})
        systems = [m["system"] for m in r["mappings"]]
        assert "primary_zone" in systems
        pz = next(m for m in r["mappings"] if m["system"] == "primary_zone")
        assert pz["code"] == "农业空间"


class TestMapCodeGhytbmInput:
    """map_code with GHYTBM (appendix5) code input."""

    def test_ghytbm_returns_vne_mapping(self):
        r = map_code.invoke({"code_or_name": "2121"})
        assert r["input"]["system"] == "appendix5"
        systems = [m["system"] for m in r["mappings"]]
        assert "vne_code" in systems

    def test_ghytbm_returns_zone_type(self):
        r = map_code.invoke({"code_or_name": "2121"})
        systems = [m["system"] for m in r["mappings"]]
        assert "zone_type_appendix5" in systems


class TestMapCodePlanningZoneInput:
    """map_code with planning_zone input."""

    def test_planning_zone_returns_primary_zone(self):
        r = map_code.invoke({"code_or_name": "村庄建设区"})
        assert r["input"]["system"] == "planning_zone"
        systems = [m["system"] for m in r["mappings"]]
        assert "primary_zone" in systems
        pz = next(m for m in r["mappings"] if m["system"] == "primary_zone")
        # v3.0 校正: 城镇空间
        assert pz["code"] == "城镇空间"

    def test_planning_zone_returns_space_control(self):
        r = map_code.invoke({"code_or_name": "村庄建设区"})
        systems = [m["system"] for m in r["mappings"]]
        assert "space_control" in systems


class TestMapCodeMappingFields:
    """Each mapping suggestion must include code + name + rule + confidence."""

    def test_all_mappings_have_required_fields(self):
        r = map_code.invoke({"code_or_name": "0101"})
        for m in r["mappings"]:
            assert "system" in m
            assert "code" in m
            assert "name" in m
            assert "rule" in m
            assert "confidence" in m

    def test_all_mappings_have_nonempty_code(self):
        r = map_code.invoke({"code_or_name": "0101"})
        for m in r["mappings"]:
            assert m["code"], f"Empty code in mapping: {m}"


class TestMapCodeEdgeCases:
    """Edge cases: unknown input, empty input."""

    def test_unknown_input_returns_empty_mappings(self):
        r = map_code.invoke({"code_or_name": "ZZZZZZZZZ"})
        assert r["input"]["system"] == "unknown"
        assert r["mappings"] == []

    def test_empty_input(self):
        r = map_code.invoke({"code_or_name": ""})
        assert r["mappings"] == []
