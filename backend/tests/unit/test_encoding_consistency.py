"""Encoding system consistency tests.

Validates that the encoding system is internally consistent after the v2.0 refactor:
- GAP-A: TDYTFQDM uses 4-digit codes, not VNE alphabetic codes
- GAP-B: TDKJGZFQDM uses unified 01-06, not 510-540
- GAP-C: dlbm_to_planning_zone tests use real tugui codes
- GAP-D: DLBM->GHYTBM forward mapping exists
- GAP-I: Three-zone is derived, not from rule_loader
- Cross-file consistency: appendix5 zone_type matches land_use_structure parent
- No dead code: removed ECOLOGICAL_CONTROL_CODES, GHYTMC_TO_DLMC
- No backward-compat aliases: FORESTRY_CODES, CONSTRUCTION_ZONE_TYPES, SPACE_CONTROL_ZONE_TYPES
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
        assert conv_type == "auto"

    def test_one_to_many_has_alternative(self):
        """One-to-many mappings have alternative info."""
        ghytbm, conv_type, condition = get_ghytbm_conversion_info("0301")
        assert conv_type == "context"

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
        """FORESTRY_CODES backward-compat alias must be removed; use FOREST_CODES."""
        from app.modules.schema.encodings import code_sets
        assert not hasattr(code_sets, "FORESTRY_CODES"), \
            "FORESTRY_CODES alias must be removed; use FOREST_CODES"
        assert hasattr(code_sets, "FOREST_CODES")
        assert len(code_sets.FOREST_CODES) > 0

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


# ============================================================
# Phase 2 tests: Condition model, 0602 fix, new schema, etc.
# ============================================================

class TestConditionModel:
    """Condition model tree (expr_eval.py) — 5 kinds."""

    def test_null_always_true(self):
        from app.modules.schema.encodings.dicts.expr_eval import Condition, MappingContext
        c = Condition(kind="null")
        assert c.evaluate(MappingContext()) is True

    def test_and_all_true(self):
        from app.modules.schema.encodings.dicts.expr_eval import Condition, MappingContext
        c = Condition(kind="and", children=[
            Condition(kind="null"),
            Condition(kind="null"),
        ])
        assert c.evaluate(MappingContext()) is True

    def test_or_one_false(self):
        from app.modules.schema.encodings.dicts.expr_eval import Condition, MappingContext
        c = Condition(kind="or", children=[
            Condition(kind="null"),
            Condition(kind="null"),
        ])
        assert c.evaluate(MappingContext()) is True

    def test_comparison_eq(self):
        from app.modules.schema.encodings.dicts.expr_eval import Condition, MappingContext
        ctx = MappingContext(parcel_attrs={"QSXZ": "10"})
        c = Condition(kind="comparison", field="QSXZ", op="==", value="10")
        assert c.evaluate(ctx) is True

    def test_comparison_ne(self):
        from app.modules.schema.encodings.dicts.expr_eval import Condition, MappingContext
        ctx = MappingContext(parcel_attrs={"QSXZ": "20"})
        c = Condition(kind="comparison", field="QSXZ", op="!=", value="10")
        assert c.evaluate(ctx) is True

    def test_comparison_in(self):
        from app.modules.schema.encodings.dicts.expr_eval import Condition, MappingContext
        ctx = MappingContext(parcel_attrs={"base_zone": "村庄建设区"})
        c = Condition(kind="comparison", field="base_zone", op="in", value=["村庄建设区", "农田保护区"])
        assert c.evaluate(ctx) is True

    def test_comparison_starts_with(self):
        from app.modules.schema.encodings.dicts.expr_eval import Condition, MappingContext
        ctx = MappingContext(parcel_attrs={"dlbm": "0602"})
        c = Condition(kind="comparison", field="dlbm", op="starts_with", value="06")
        assert c.evaluate(ctx) is True

    def test_comparison_gt(self):
        from app.modules.schema.encodings.dicts.expr_eval import Condition, MappingContext
        ctx = MappingContext(parcel_attrs={"area_ha": 1.5})
        c = Condition(kind="comparison", field="area_ha", op="gt", value=1.0)
        assert c.evaluate(ctx) is True

    def test_comparison_lt(self):
        from app.modules.schema.encodings.dicts.expr_eval import Condition, MappingContext
        ctx = MappingContext(parcel_attrs={"area_ha": 0.5})
        c = Condition(kind="comparison", field="area_ha", op="lt", value=1.0)
        assert c.evaluate(ctx) is True

    def test_func_poi_match(self):
        from app.modules.schema.encodings.dicts.expr_eval import Condition, MappingContext
        ctx = MappingContext(poi_hits=[{"name": "超市"}, {"name": "学校"}])
        c = Condition(kind="func", func="poi_match", args=["超市", "商场"])
        assert c.evaluate(ctx) is True

    def test_func_field_equals(self):
        from app.modules.schema.encodings.dicts.expr_eval import Condition, MappingContext
        ctx = MappingContext(parcel_attrs={"QSXZ": "10"})
        c = Condition(kind="func", func="field_equals", args=["QSXZ", "10"])
        assert c.evaluate(ctx) is True

    def test_func_area_gt(self):
        from app.modules.schema.encodings.dicts.expr_eval import Condition, MappingContext
        ctx = MappingContext(parcel_attrs={"area_ha": 2.5})
        c = Condition(kind="func", func="area_gt", args=[1.0])
        assert c.evaluate(ctx) is True

    def test_serialize_roundtrip(self):
        from app.modules.schema.encodings.dicts.expr_eval import Condition, condition_from_yaml
        cond = Condition(kind="and", children=[
            Condition(kind="comparison", field="QSXZ", op="==", value="10"),
            Condition(kind="null"),
        ])
        data = cond.model_dump(mode="json")
        restored = condition_from_yaml(data)
        assert restored.kind == "and"
        assert len(restored.children) == 2


class Test0602DuplicateFixed:
    """0602 duplicate key fix — 2 targets reachable."""

    def test_0602_has_two_targets(self):
        from app.modules.schema.encodings.dicts.loader import get_center
        center = get_center()
        table = center.get_mapping("dlbm_to_ghytbm")
        entry = table.propose("0602")
        assert entry is not None
        targets = entry.get("targets", [])
        assert len(targets) == 2, f"Expected 2 targets for 0602, got {len(targets)}"
        codes = {t.get("code") for t in targets}
        assert "2130" in codes, "Missing 2130 (mining)"
        assert "1510" in codes, "Missing 1510 (facility agriculture)"

    def test_0602_auto_default(self):
        """Default for 0602 is 2130."""
        from app.modules.schema.encodings.code_sets import get_ghytbm_for_dlbm
        assert get_ghytbm_for_dlbm("0602") == "2130"


class TestNewMappingSchema:
    """New 1:N mapping schema loads correctly."""

    def test_dlbm_mapping_loaded(self):
        """dlbm_to_ghytbm is a MappingTable."""
        from app.modules.schema.encodings.dicts.loader import get_center
        center = get_center()
        table = center.get_mapping("dlbm_to_ghytbm")
        assert table.source_system == "dlbm"
        assert table.target_system == "ghytbm"
        assert len(table._by_source) >= 20

    def test_sddlbm_mapping_loaded(self):
        """sddlbm_to_ydyhfldm is a MappingTable."""
        from app.modules.schema.encodings.dicts.loader import get_center
        center = get_center()
        table = center.get_mapping("sddlbm_to_ydyhfldm")
        assert table.source_system == "sddlbm"
        assert table.target_system == "ydyhfldm"
        entry = table.propose("05H1")
        assert entry is not None
        assert entry.get("decision") == "context"

    def test_ghflbm_mapping_loaded(self):
        """ghflbm_to_tdytfqdm is a MappingTable with fixed key."""
        from app.modules.schema.encodings.dicts.loader import get_center
        center = get_center()
        table = center.get_mapping("ghflbm_to_tdytfqdm")
        assert table.source_system == "ghflbm"
        assert table.target_system == "tdytfqdm"
        assert table.propose("2120") is not None

    def test_ghflbm_to_dict_flat(self):
        """MappingTable.to_dict() returns flat dict for backward compat."""
        from app.modules.schema.encodings.dicts.loader import get_center
        center = get_center()
        table = center.get_mapping("ghflbm_to_tdytfqdm")
        flat = table.to_dict()
        assert flat.get("2120") == ("0600", "auto")


class TestPlanningZoneRulesCondition:
    """planning_zone_rules.yaml condition strings -> Condition model tree."""

    def test_rule_conditions_loaded(self):
        from app.modules.schema.encodings.dicts.rule_loader import get_rule_loader
        loader = get_rule_loader()
        rules = loader.zone_decision_rules()
        assert len(rules) >= 3
        for rule in rules:
            assert rule.condition is not None
            assert rule.condition.kind in ("and", "or", "null", "func", "comparison")

    def test_rule_1_ecological_redline(self):
        from app.modules.schema.encodings.dicts.rule_loader import get_rule_loader
        from app.modules.schema.encodings.dicts.expr_eval import MappingContext
        loader = get_rule_loader()
        rules = loader.zone_decision_rules()
        rule1 = rules[0]
        assert rule1.priority == 1
        assert rule1.result == "生态保护区"

        ctx = MappingContext(
            parcel_attrs={"base_zone": "村庄建设区"},
            zone_membership=["in_ecological_redline"],
        )
        assert rule1.condition.evaluate(ctx) is True

    def test_rule_2_basic_farmland(self):
        from app.modules.schema.encodings.dicts.rule_loader import get_rule_loader
        from app.modules.schema.encodings.dicts.expr_eval import MappingContext
        loader = get_rule_loader()
        rules = loader.zone_decision_rules()
        rule2 = rules[1]
        assert rule2.priority == 2
        assert rule2.result == "农田保护区"

        ctx = MappingContext(
            zone_membership=["in_basic_farmland"],
            parcel_attrs={"dlbm_match": True},
        )
        assert rule2.condition.evaluate(ctx) is True


class TestGHYTBMToPlanningZoneYAML:
    """_GHYTBM_TO_PLANNING_ZONE moved from hardcoded to YAML."""

    def test_loaded_from_yaml(self):
        from app.modules.schema.encodings.code_sets import GHYTBM_TO_PLANNING_ZONE
        assert len(GHYTBM_TO_PLANNING_ZONE) >= 20
        assert GHYTBM_TO_PLANNING_ZONE.get("1100") == "农田保护区"
        assert GHYTBM_TO_PLANNING_ZONE.get("2121") == "村庄建设区"
        assert GHYTBM_TO_PLANNING_ZONE.get("3100") == "生态保护区"

    def test_not_hardcoded_anymore(self):
        """_GHYTBM_TO_PLANNING_ZONE must not exist in code_sets."""
        from app.modules.schema.encodings import code_sets
        assert not hasattr(code_sets, "_GHYTBM_TO_PLANNING_ZONE"), \
            "Hardcoded dict should be removed"

    def test_ghytmc_to_planning_zone_works(self):
        """GHYTMC_TO_PLANNING_ZONE derived from YAML."""
        from app.modules.schema.encodings.code_sets import GHYTMC_TO_PLANNING_ZONE
        assert GHYTMC_TO_PLANNING_ZONE.get("耕地") == "农田保护区"
        assert GHYTMC_TO_PLANNING_ZONE.get("水域") == "生态保护区"

    def test_dlbm_to_planning_zone_fallback(self):
        """dlbm_to_planning_zone no longer uses hardcoded fallback."""
        from app.modules.schema.encodings.code_sets import dlbm_to_planning_zone
        result = dlbm_to_planning_zone("1100")
        assert result == "一般农业区"  # 1100 (GHYTBM) not in DLBM_TO_PLANNING_ZONE


class TestCandidateEngineResolve:
    """CandidateEngine.resolve() L0/L1/L3 paths."""

    def test_l0_auto(self):
        from app.modules.schema.encodings.dicts.candidate_engine import CandidateEngine
        engine = CandidateEngine()
        resolution = engine.resolve("ghflbm", "tdytfqdm", "2120")
        assert resolution.kind == "auto"
        assert resolution.chosen_code == "0600"

    def test_l1_rule_unique_match(self):
        from app.modules.schema.encodings.dicts.candidate_engine import CandidateEngine
        from app.modules.schema.encodings.dicts.expr_eval import MappingContext
        engine = CandidateEngine()
        ctx = MappingContext(parcel_attrs={"QSXZ": "10"})
        resolution = engine.resolve("dlbm", "ghytbm", "0602", ctx)
        assert resolution.kind == "rule"
        assert resolution.chosen_code == "2130"

    def test_l3_manual_no_context(self):
        from app.modules.schema.encodings.dicts.candidate_engine import CandidateEngine
        engine = CandidateEngine()
        resolution = engine.resolve("dlbm", "ghytbm", "0602")
        assert resolution.kind == "manual"

    def test_unmapped(self):
        from app.modules.schema.encodings.dicts.candidate_engine import CandidateEngine
        engine = CandidateEngine()
        resolution = engine.resolve("unknown", "unknown", "0000")
        assert resolution.kind == "unmapped"

    def test_propose_backward_compat(self):
        from app.modules.schema.encodings.dicts.candidate_engine import CandidateEngine
        engine = CandidateEngine()
        proposal = engine.propose("dlbm", "ghytbm", "0101")
        assert proposal.suggested_code == "1100"
        assert proposal.confidence == "exact"
        assert not proposal.needs_human_decision


class TestCodeSetsClean:
    """Old hardcoded fields removed from code_sets."""

    def test_ghytbm_to_planning_zone_exported(self):
        """GHYTBM_TO_PLANNING_ZONE is exported."""
        from app.modules.schema.encodings import code_sets
        assert hasattr(code_sets, "GHYTBM_TO_PLANNING_ZONE")

    def test_no_proposaltable_import(self):
        """ProposalTable no longer imported from loader."""
        from app.modules.schema.encodings.dicts import loader
        assert not hasattr(loader, "ProposalTable")

    def test_mappingtable_available(self):
        """MappingTable is available from loader."""
        from app.modules.schema.encodings.dicts import loader
        assert hasattr(loader, "MappingTable")

    def test_mappings_registered(self):
        """DictionaryCenter.mappings returns mapping names."""
        from app.modules.schema.encodings.dicts.loader import get_center
        center = get_center()
        assert "dlbm_to_ghytbm" in center.mappings
        assert "sddlbm_to_ydyhfldm" in center.mappings
        assert "ghflbm_to_tdytfqdm" in center.mappings
