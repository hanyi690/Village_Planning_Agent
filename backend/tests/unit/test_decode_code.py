"""Unit tests for decode_code tool (v3.0).

Tests auto-detection of 14 encoding systems + system description output.
"""
import pytest

from app.tools.gis.lookup import decode_code


class TestDecodeCodeBasic:
    """decode_code auto-detects encoding system and returns name."""

    def test_dlbm_detected(self):
        r = decode_code.invoke({"code": "0101"})
        assert r["detected_system"] == "gbt21010"
        assert r["name"] == "水田"
        assert "GB/T 21010" in r["system_description"]

    def test_ghytbm_detected(self):
        r = decode_code.invoke({"code": "2121"})
        assert r["detected_system"] == "appendix5"
        assert r["name"] == "宅基地"

    def test_vne_detected(self):
        r = decode_code.invoke({"code": "V11"})
        assert r["detected_system"] == "vne_code"
        assert r["name"] == "住宅用地"

    def test_space_control_detected(self):
        r = decode_code.invoke({"code": "01"})
        assert r["detected_system"] == "space_control"
        assert r["name"] == "允许建设区"

    def test_gbt50137_letter_code_detected(self):
        r = decode_code.invoke({"code": "R"})
        assert r["detected_system"] == "zone_type_gbt50137"
        assert r["name"] == "居住用地"

    def test_planning_zone_chinese_name_detected(self):
        r = decode_code.invoke({"code": "生态保护区"})
        assert r["detected_system"] == "planning_zone"
        assert r["name"] == "生态保护区"

    def test_primary_zone_chinese_name_detected(self):
        r = decode_code.invoke({"code": "城镇空间"})
        assert r["detected_system"] == "primary_zone"
        assert r["name"] == "城镇空间"

    def test_three_categories_detected(self):
        r = decode_code.invoke({"code": "农用地"})
        assert r["detected_system"] == "three_categories"
        assert r["name"] == "农用地"


class TestDecodeCodeEdgeCases:
    """Edge cases: empty, unknown, whitespace."""

    def test_empty_code(self):
        r = decode_code.invoke({"code": ""})
        assert r["detected_system"] == "unknown"
        assert r["name"] == ""

    def test_unknown_code(self):
        r = decode_code.invoke({"code": "ZZZZZZZZZ"})
        assert r["detected_system"] == "unknown"
        assert r["name"] == ""

    def test_whitespace_stripped(self):
        r = decode_code.invoke({"code": "  0101  "})
        assert r["detected_system"] == "gbt21010"
        assert r["name"] == "水田"


class TestDecodeCodeSystemDescription:
    """System description is always populated for known systems."""

    def test_description_populated_for_known(self):
        r = decode_code.invoke({"code": "0101"})
        assert r["system_description"]
        assert len(r["system_description"]) > 10

    def test_description_empty_for_unknown(self):
        r = decode_code.invoke({"code": "ZZZ"})
        assert r["system_description"] == ""
