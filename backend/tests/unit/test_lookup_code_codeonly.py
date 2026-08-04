"""Unit tests for refactored lookup_land_use_code tool (v3.0).

Verifies CODE-ONLY output: no ghytmc/dlmc name fields in result.
Names must be obtained separately via decode_code.
"""
import pytest

from app.tools.gis.lookup import lookup_land_use_code


class TestLookupLandUseCodeBasic:
    """Basic name -> code lookup."""

    def test_zhaiji_returns_ghytbm(self):
        r = lookup_land_use_code.invoke({"land_use_name": "宅基地"})
        assert r["success"] is True
        data = r["data"]
        assert data["ghytbm"] == "2121"

    def test_unknown_name_returns_failure(self):
        r = lookup_land_use_code.invoke({"land_use_name": "不存在的地类ZZZ"})
        assert r["success"] is False


class TestCodeOnlyOutput:
    """v3.0: Output must NOT contain name fields (ghytmc, dlmc)."""

    def test_no_ghytmc_in_top_level(self):
        r = lookup_land_use_code.invoke({"land_use_name": "宅基地"})
        data = r["data"]
        assert "ghytmc" not in data, f"ghytmc should be removed, got: {data}"

    def test_no_dlmc_in_top_level(self):
        r = lookup_land_use_code.invoke({"land_use_name": "宅基地"})
        data = r["data"]
        assert "dlmc" not in data, f"dlmc should be removed, got: {data}"

    def test_no_ghytmc_in_candidates_ghytbm(self):
        r = lookup_land_use_code.invoke({"land_use_name": "宅基地"})
        for cand in r["data"].get("candidates_ghytbm", []):
            assert "ghytmc" not in cand, f"ghytmc in candidate: {cand}"

    def test_no_dlmc_in_candidates_dlbm(self):
        r = lookup_land_use_code.invoke({"land_use_name": "宅基地"})
        for cand in r["data"].get("candidates_dlbm", []):
            assert "dlmc" not in cand, f"dlmc in candidate: {cand}"

    def test_no_ghytmc_in_ghflbm_match(self):
        r = lookup_land_use_code.invoke({"land_use_name": "宅基地"})
        # GHFLBMMatch should not have ghytmc field
        from app.tools.gis.lookup import GHFLBMMatch
        fields = GHFLBMMatch.model_fields
        assert "ghytmc" not in fields


class TestExpectedFieldsPresent:
    """Same-system code fields that should still be present."""

    def test_ghytbm_present(self):
        r = lookup_land_use_code.invoke({"land_use_name": "宅基地"})
        assert "ghytbm" in r["data"]

    def test_dlbm_aliases_present(self):
        r = lookup_land_use_code.invoke({"land_use_name": "宅基地"})
        assert "dlbm_aliases" in r["data"]

    def test_candidates_present(self):
        r = lookup_land_use_code.invoke({"land_use_name": "宅基地"})
        assert "candidates_ghytbm" in r["data"]
        assert "candidates_dlbm" in r["data"]


class TestNoCrossSystemDerivedFields:
    """v4.0 (Wave A.1): cross-system derived fields must NOT be exposed."""

    def test_no_zone_type(self):
        r = lookup_land_use_code.invoke({"land_use_name": "宅基地"})
        assert "zone_type" not in r["data"]

    def test_no_vne_code(self):
        r = lookup_land_use_code.invoke({"land_use_name": "宅基地"})
        assert "vne_code" not in r["data"]

    def test_no_cross_system_in_candidates(self):
        r = lookup_land_use_code.invoke({"land_use_name": "宅基地"})
        for cand in r["data"].get("candidates_ghytbm", []):
            assert "zone_type" not in cand
            assert "vne_code" not in cand
