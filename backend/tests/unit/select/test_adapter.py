"""Tests for GroundingResult -> CandidateParcel adapter."""

import pytest

from app.agent.select.adapter import candidate_site_to_parcels, grounding_to_candidate_parcels
from app.modules.schema import DLBM_TO_DLMC
from app.modules.schema.contracts.grounding_contracts import CandidateSite, GroundingResult

from .conftest import make_parcel


def test_empty_result_returns_empty(make_bundle):
    result = GroundingResult()
    assert grounding_to_candidate_parcels(result, make_bundle()) == []


def test_single_site_two_parcels(make_bundle):
    site = CandidateSite(site_id="s1", source_parcels=["P001", "P002"])
    result = GroundingResult(candidates=[site])
    parcels = grounding_to_candidate_parcels(result, make_bundle())
    assert len(parcels) == 2
    p001 = next(p for p in parcels if p.bsm == "P001")
    assert p001.area_ha == pytest.approx(1.2)
    assert p001.dlbm == "0101"
    assert p001.dlmc == DLBM_TO_DLMC.get("0101", "")
    assert p001.geometry["type"] == "Polygon"


def test_unknown_bsm_skipped(make_bundle):
    site = CandidateSite(site_id="s1", source_parcels=["P001", "UNKNOWN"])
    result = GroundingResult(candidates=[site])
    parcels = grounding_to_candidate_parcels(result, make_bundle())
    assert len(parcels) == 1
    assert parcels[0].bsm == "P001"


def test_site_with_empty_source_parcels(make_bundle):
    site = CandidateSite(site_id="s1", source_parcels=[])
    result = GroundingResult(candidates=[site])
    assert grounding_to_candidate_parcels(result, make_bundle()) == []


def test_candidate_site_to_parcels_direct(make_bundle):
    parcel_by_bsm = {"P001": make_parcel("P001"), "P002": make_parcel("P002")}
    site = CandidateSite(site_id="s1", source_parcels=["P001", "P002"])
    parcels = candidate_site_to_parcels(site, parcel_by_bsm)
    assert [p.bsm for p in parcels] == ["P001", "P002"]
    assert parcels[0].dlmc == DLBM_TO_DLMC.get("0101", "")


def test_missing_attributes_robust():
    from types import SimpleNamespace

    bare = SimpleNamespace(bsm="P999", geometry={"type": "Polygon", "coordinates": []})
    parcel_by_bsm = {"P999": bare}
    site = CandidateSite(site_id="s1", source_parcels=["P999"])
    parcels = candidate_site_to_parcels(site, parcel_by_bsm)
    assert len(parcels) == 1
    assert parcels[0].dlbm == ""
    assert parcels[0].dlmc == ""
    assert parcels[0].area_ha == 0.0
