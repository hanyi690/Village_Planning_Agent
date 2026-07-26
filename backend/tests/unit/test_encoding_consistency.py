"""Encoding system consistency tests.

Validates that the encoding system is internally consistent after the v2.0 refactor:
- GAP-A: TDYTFQDM uses 4-digit codes, not VNE alphabetic codes
- GAP-B: TDKJGZFQDM uses unified 01-06, not 510-540
- GAP-C: dlbm_to_planning_zone tests use real tugui codes
- GAP-D: DLBM->GHYTBM forward mapping exists
- GAP-I: Three-zone is derived, not from rule_loader
- Cross-file consistency: appendix5 zone_type matches land_use_structure parent
- No dead code: removed FORESTRY_CODES, ECOLOGICAL_CONTROL_CODES, GHYTMC_TO_DLMC
"""

import pytest

from app.modules.schema.encodings.code_sets import (
    SPACE_CONTROL_ZONE_CODES,
    SPACE_CONTROL_ZONE_COLORS,
    SPACE_CONTROL_NAME_TO_CODE,
    PLANNING_ZONE_TO_CONTROL_CODE,
    PLANNING_ZONE_TO_PRIMARY_ZONE,
    GHFLBM_TO_TDYTFQDM,
    GHFLBM_TO_TDYT_NAME,
    DLBM_TO_GHYTBM,
    DLBM_TO_GHYTBM_CONVERSIONS,
    GHYTBM_TO_ZONE_TYPE,
    GHYTBM_TO_GHYTMC,
    GHFLBM_TO_GHYTBMS,
    DLBM_TO_ZONE_TYPE,
    DLBM_TO_PLANNING_ZONE,
    get_tdytfqdm_for_ghflbm,
    get_tdyt_name_for_ghflbm,
    get_space_control_name,
    get_space_control_code,
    get_ghytbm_for_dlbm,
    get_ghytbm_conversion_info,
    dlbm_to_planning_zone,
    get_primary_zone,
)


class TestTDKJGZFQDMUnified:
    """GAP-B: TDKJGZFQDM uses unified 01-06, not 510-540."""

    def test_codes_are_01_06_not_510_540(self):
        """All codes are 2-digit 01-06, never 3-digit 510-540."""
        for code in SPACE_CONTROL_ZONE_CODES:
            assert code in ("01", "02", "03", "04", "05", "06"), f"Unexpected code: {code}"

    def test_has_6_zones(self):
        """Must have exactly 6 zones (including farmland + ecological)."""
        assert len(SPACE_CONTROL_ZONE_CODES) == 6

    def test_has_colors_for_all(self):
        """Every code has a color."""
        for code in SPACE_CONTROL_ZONE_CODES:
            assert code in SPACE_CONTROL_ZONE_COLORS, f"Missing color for {code}"

    def test_name_to_code_reverse(self):
        """Reverse lookup works."""
        assert get_space_control_code("允许建设区") == "01"
        assert get_space_control_code("禁止建设区") == "04"
        assert get_space_control_name("01") == "允许建设区"

    def test_planning_zone_to_control_code(self):
        """Planning zone -> control code mapping exists."""
        assert PLANNING_ZONE_TO_CONTROL_CODE.get("村庄建设区") == "01"
        assert PLANNING_ZONE_TO_CONTROL_CODE.get("农田保护区") == "05"
        assert PLANNING_ZONE_TO_CONTROL_CODE.get("生态保护区") == "04"


class TestTDYTFQDMCorrect:
    """GAP-A: TDYTFQDM uses 4-digit township codes, not VNE alphabetic."""

    def test_ghflbm_to_tdytfqdm_exists(self):
        """Mapping is populated."""
        assert len(GHFLBM_TO_TDYTFQDM) > 0

    def test_tdytfqdm_is_4_digit(self):
        """All TDYTFQDM values are 4-digit numeric codes, not VNE letters."""
        for ghflbm, tdytfqdm in GHFLBM_TO_TDYTFQDM.items():
            assert len(tdytfqdm) == 4, f"TDYTFQDM {tdytfqdm} for GHFLBM {ghflbm} is not 4-digit"
            assert tdytfqdm.isdigit(), f"TDYTFQDM {tdytfqdm} is not numeric (VNE leak?)"

    def test_lookup_function(self):
        """get_tdytfqdm_for_ghflbm works."""
        assert get_tdytfqdm_for_ghflbm("2120") == "0600"
        assert get_tdytfqdm_for_ghflbm("1110") == "0100"
        assert get_tdytfqdm_for_ghflbm("UNKNOWN") == ""

    def test_name_lookup(self):
        """get_tdyt_name_for_ghflbm works."""
        assert "农业" in get_tdyt_name_for_ghflbm("1110") or "农业" in get_tdyt_name_for_ghflbm("2120")


class TestDLBMToGHYTBMMapping:
    """GAP-D: DLBM->GHYTBM forward mapping exists."""

    def test_mapping_populated(self):
        """Mapping has entries."""
        assert len(DLBM_TO_GHYTBM) >= 20

    def test_known_mappings(self):
        """Key mappings are correct."""
        assert DLBM_TO_GHYTBM.get("0101") == "1100"  # 水田 -> 耕地
        assert DLBM_TO_GHYTBM.get("0702") == "2121"  # 农村宅基地 -> 宅基地
        assert DLBM_TO_GHYTBM.get("1101") == "3100"  # 河流水面 -> 水域

    def test_conversion_info(self):
        """Conversion type is available."""
        ghytbm, conv_type, condition = get_ghytbm_conversion_info("0101")
        assert ghytbm == "1100"
        assert conv_type == "一一对应"

    def test_one_to_many_has_alternative(self):
        """One-to-many mappings have alternative info."""
        ghytbm, conv_type, condition = get_ghytbm_conversion_info("0301")
        assert conv_type == "一对多"
        assert "商品林" in condition or "生态林" in condition

    def test_lookup_function(self):
        """get_ghytbm_for_dlbm works."""
        assert get_ghytbm_for_dlbm("0101") == "1100"
        assert get_ghytbm_for_dlbm("UNKNOWN") == ""


class TestPLanningZoneToPrimaryZone:
    """PLANNING_ZONE_TO_PRIMARY_ZONE loaded from YAML, not hardcoded."""

    def test_has_6_entries(self):
        assert len(PLANNING_ZONE_TO_PRIMARY_ZONE) == 6

    def test_values_correct(self):
        assert PLANNING_ZONE_TO_PRIMARY_ZONE["村庄建设区"] == "建设空间"
        assert PLANNING_ZONE_TO_PRIMARY_ZONE["农田保护区"] == "农业空间"
        assert PLANNING_ZONE_TO_PRIMARY_ZONE["生态保护区"] == "生态空间"


class TestCrossFileConsistency:
    """appendix5 zone_type should be consistent with land_use_structure parent."""

    def test_1400_caodeng_is_ecological(self):
        """GAP-46: 1400 草地 zone_type=生态绿地 in appendix5, parent should be 生态用地."""
        assert GHYTBM_TO_ZONE_TYPE.get("1400") == "生态绿地"

    def test_3200_ziranbaoliu_is_agriculture(self):
        """GAP-48: 3200 自然保留地 zone_type=农业用地 in appendix5."""
        assert GHYTBM_TO_ZONE_TYPE.get("3200") == "农业用地"

    def test_1500_ydyhfldm_not_special(self):
        """GAP-24: 1500 ydyhfldm should be 2300 (其他土地), not 1500 (特殊用地)."""
        from app.modules.schema.encodings.code_sets import GHYTBM_TO_YDYHFLDM
        assert GHYTBM_TO_YDYHFLDM.get("1500") == "2300"

    def test_v31_zone_type_is_industry(self):
        """GAP-31: V31 zone_type should be 产业用地 (matching appendix5 2124)."""
        from app.modules.schema.encodings.code_sets import VNE_TO_ZONE_TYPE
        assert VNE_TO_ZONE_TYPE.get("V31") == "产业用地"


class TestDeadCodeRemoved:
    """v2.0: Dead code should be removed or not exported."""

    def test_forestry_codes_not_exported(self):
        """FORESTRY_CODES was dead (empty set), should not be in __all__."""
        from app.modules.schema.encodings import code_sets
        assert not hasattr(code_sets, "FORESTRY_CODES") or code_sets.FORESTRY_CODES == set()

    def test_ecological_control_codes_not_exported(self):
        """ECOLOGICAL_CONTROL_CODES was dead (empty set), should not be in __all__."""
        from app.modules.schema.encodings import code_sets
        assert not hasattr(code_sets, "ECOLOGICAL_CONTROL_CODES")

    def test_ghytmc_to_dlmc_not_exported(self):
        """GHYTMC_TO_DLMC was identity mapping, should not exist."""
        from app.modules.schema.encodings import code_sets
        assert not hasattr(code_sets, "GHYTMC_TO_DLMC")


class TestDLBMPlanningZoneRealCodes:
    """GAP-C: Test with real tugui codes, not codes that only pass by default."""

    def test_tugui_code_0110_is_farmland_protection(self):
        """0110 水田 is a real tugui code -> 农田保护区."""
        result = dlbm_to_planning_zone("0110")
        assert result == "农田保护区", f"Expected 农田保护区, got {result}"

    def test_tugui_code_2030_is_village_construction(self):
        """2030 农村居民点 -> 村庄建设区."""
        result = dlbm_to_planning_zone("2030")
        assert result == "村庄建设区", f"Expected 村庄建设区, got {result}"

    def test_unknown_code_returns_default(self):
        """Unknown code returns default, not None."""
        result = dlbm_to_planning_zone("XXXX")
        assert result == "一般农业区"

    def test_primary_zone_for_0110(self):
        """0110 -> 农业空间."""
        assert get_primary_zone("0110") == "农业空间"

    def test_primary_zone_for_2030(self):
        """2030 -> 建设空间."""
        assert get_primary_zone("2030") == "建设空间"
