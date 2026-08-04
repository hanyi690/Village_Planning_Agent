"""Tests for derivation helpers in enrichment.py (Wave A.1).

BaseFacts only keep same-system facts (DLBM code → DLMC name). Cross-system
derivations (DLBM→zone_type, planning_zone→control_code) are removed.
"""
from app.modules.kg.builder.enrichment import (
    derive_semantic_label, derive_taxonomic_parent,
    derive_legal_constraint, get_allowed_operations,
    CONTROL_CODE_TO_CONSTRAINT,
    get_gis_layer_group_info, get_all_gis_layer_groups,
    REGULATION_TYPES,
)


class TestDeriveSemanticLabel:
    def test_known_dlbm_returns_dlmc_name(self):
        result = derive_semantic_label("0101")
        assert result == "水田"

    def test_empty_dlbm(self):
        assert derive_semantic_label("") == ""

    def test_unknown_dlbm_returns_empty(self):
        # no cross-system zone_type fallback anymore
        assert derive_semantic_label("9999") == ""


class TestDeriveTaxonomicParentRemoved:
    def test_returns_empty(self):
        """Cross-system DLBM→zone_type derivation removed from BaseFacts."""
        assert derive_taxonomic_parent("0101") == ""


class TestDeriveLegalConstraintRemoved:
    def test_returns_empty(self):
        """Cross-system planning_zone→control_code derivation removed."""
        assert derive_legal_constraint("农田保护区") == ""

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