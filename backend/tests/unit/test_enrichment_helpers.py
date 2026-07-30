"""Tests for derivation helpers moved to enrichment.py."""
from app.modules.kg.builder.enrichment import (
    derive_semantic_label, derive_taxonomic_parent,
    derive_legal_constraint, get_allowed_operations,
    CONTROL_CODE_TO_CONSTRAINT,
    get_gis_layer_group_info, get_all_gis_layer_groups,
    REGULATION_TYPES,
)


class TestDeriveSemanticLabel:
    def test_known_dlbm(self):
        result = derive_semantic_label("0101")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_empty_dlbm(self):
        assert derive_semantic_label("") == ""

    def test_unknown_dlbm_falls_back(self):
        result = derive_semantic_label("9999")
        assert isinstance(result, str)


class TestDeriveLegalConstraint:
    def test_known_zone(self):
        result = derive_legal_constraint("农田保护区")
        assert result == "forbid_construction"

    def test_empty_zone(self):
        assert derive_legal_constraint("") == ""


class TestControlCodeToConstraint:
    def test_code_05_is_forbid(self):
        assert CONTROL_CODE_TO_CONSTRAINT["05"] == "forbid_construction"

    def test_code_01_is_allow(self):
        assert CONTROL_CODE_TO_CONSTRAINT["01"] == "allow_construction"


class TestGisLayerGroupInfo:
    def test_returns_dict_for_known_group(self):
        result = get_gis_layer_group_info("current_landuse")
        assert isinstance(result, dict)

    def test_returns_empty_for_unknown(self):
        result = get_gis_layer_group_info("nonexistent_group")
        assert result == {}


class TestRegulationTypes:
    def test_has_farmland(self):
        assert "永久基本农田保护" in REGULATION_TYPES