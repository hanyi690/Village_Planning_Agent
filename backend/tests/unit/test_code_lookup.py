"""Unit tests for app.utils.code_lookup helper (v3.0).

Tests the internal lookup_code_name function across 14 encoding systems.
Verifies forward-only (code->name), 1:1 deterministic, no code->code chains.
"""
import pytest

from app.utils.code_lookup import (
    lookup_code_name,
    ENTITY_TYPE_CN,
    RELATION_PRED_CN,
    NAME_BY_CODE,
)


class TestLookupCodeNameBasic:
    """Basic forward code->name lookups per encoding system."""

    def test_dlbm_known(self):
        assert lookup_code_name("dlbm", "0101") == "水田"
        assert lookup_code_name("dlbm", "0702") == "农村宅基地"

    def test_dlbm_unknown_returns_empty(self):
        assert lookup_code_name("dlbm", "9999") == ""

    def test_dlbm_empty_input(self):
        assert lookup_code_name("dlbm", "") == ""
        assert lookup_code_name("dlbm", None) == ""

    def test_ghytbm_known(self):
        assert lookup_code_name("ghytbm", "2121") == "宅基地"

    def test_ghytbm_unknown_returns_empty(self):
        assert lookup_code_name("ghytbm", "XXXX") == ""

    def test_vne_code_known(self):
        assert lookup_code_name("vne_code", "V11") == "住宅用地"
        assert lookup_code_name("vne_code", "E9") == "其他非建设用地"

    def test_space_control_known(self):
        assert lookup_code_name("space_control", "01") == "允许建设区"
        assert lookup_code_name("space_control", "04") == "禁止建设区"

    def test_zone_type_appendix5_known(self):
        # zone_type_appendix5 uses Chinese name as code (identity dict)
        assert lookup_code_name("zone_type_appendix5", "农业用地") == "农业用地"
        assert lookup_code_name("zone_type_appendix5", "居住用地") == "居住用地"

    def test_zone_type_gbt50137_known(self):
        assert lookup_code_name("zone_type_gbt50137", "R") == "居住用地"
        assert lookup_code_name("zone_type_gbt50137", "M") == "工业用地"

    def test_planning_zone_known(self):
        assert lookup_code_name("planning_zone", "生态保护区") == "生态保护区"
        assert lookup_code_name("planning_zone", "村庄建设区") == "村庄建设区"

    def test_primary_zone_known(self):
        assert lookup_code_name("primary_zone", "生态空间") == "生态空间"
        # v3.0 校正: 城镇空间 (not 建设空间)
        assert lookup_code_name("primary_zone", "城镇空间") == "城镇空间"

    def test_three_categories_known(self):
        assert lookup_code_name("three_categories", "农用地") == "农用地"
        assert lookup_code_name("three_categories", "建设用地") == "建设用地"
        assert lookup_code_name("three_categories", "未利用地") == "未利用地"


class TestEntityTypeAndRelationPred:
    """Entity type and relation predicate lookups."""

    def test_entity_type_parcel(self):
        assert lookup_code_name("entity_type", "Parcel") == "地块"

    def test_entity_type_road(self):
        assert lookup_code_name("entity_type", "Road") == "道路"

    def test_entity_type_unknown_fallback_to_code(self):
        # Unknown entity types return the code itself (not empty)
        assert lookup_code_name("entity_type", "UnknownType") == "UnknownType"

    def test_relation_pred_sfTouches(self):
        assert lookup_code_name("relation_pred", "sfTouches") == "相邻"

    def test_relation_pred_nearby(self):
        assert lookup_code_name("relation_pred", "nearby") == "邻近"

    def test_relation_pred_unknown_fallback_to_code(self):
        assert lookup_code_name("relation_pred", "unknown_pred") == "unknown_pred"


class TestEdgeCases:
    """Edge cases: unknown code_type, whitespace, etc."""

    def test_unknown_code_type_returns_empty(self):
        assert lookup_code_name("unknown_type", "anything") == ""

    def test_whitespace_stripped(self):
        assert lookup_code_name("dlbm", "  0101  ") == "水田"

    def test_none_code_value(self):
        assert lookup_code_name("dlbm", None) == ""

    def test_empty_code_value(self):
        assert lookup_code_name("dlbm", "") == ""


class TestNoCodeToCodeChain:
    """Critical constraint: helper NEVER chains code->code mappings.

    For example, looking up "0101" (a DLBM) with code_type="ghytbm" should
    return empty, NOT silently chain dlbm->ghytbm->ghytmc.
    """

    def test_dlbm_code_not_found_in_ghytbm_table(self):
        # 0101 is a DLBM code, not a GHYTBM code
        # Helper must NOT chain dlbm->ghytbm->name
        result = lookup_code_name("ghytbm", "0101")
        assert result == "", f"Expected empty (no chain), got '{result}'"

    def test_ghytbm_code_not_found_in_dlbm_table(self):
        # 2121 is a GHYTBM code (宅基地), not a DLBM code
        result = lookup_code_name("dlbm", "2121")
        assert result == "", f"Expected empty (no chain), got '{result}'"

    def test_dlbm_code_not_found_in_vne_table(self):
        # 0101 is a DLBM code, not a VNE code
        result = lookup_code_name("vne_code", "0101")
        assert result == ""


class TestNameByCodeCompleteness:
    """Verify NAME_BY_CODE covers all expected encoding systems."""

    def test_name_by_code_has_dlbm(self):
        assert "dlbm" in NAME_BY_CODE
        assert len(NAME_BY_CODE["dlbm"]) > 50

    def test_name_by_code_has_ghytbm(self):
        assert "ghytbm" in NAME_BY_CODE
        assert len(NAME_BY_CODE["ghytbm"]) > 10

    def test_name_by_code_has_vne_code(self):
        assert "vne_code" in NAME_BY_CODE
        assert len(NAME_BY_CODE["vne_code"]) > 10

    def test_name_by_code_has_space_control(self):
        assert "space_control" in NAME_BY_CODE
        assert len(NAME_BY_CODE["space_control"]) == 6

    def test_name_by_code_has_planning_zone(self):
        assert "planning_zone" in NAME_BY_CODE
        assert len(NAME_BY_CODE["planning_zone"]) == 6

    def test_name_by_code_has_primary_zone(self):
        assert "primary_zone" in NAME_BY_CODE
        # v3.0 校正: 3 zones including 城镇空间
        assert "城镇空间" in NAME_BY_CODE["primary_zone"].values()

    def test_name_by_code_has_three_categories(self):
        assert "three_categories" in NAME_BY_CODE
        assert len(NAME_BY_CODE["three_categories"]) == 3
