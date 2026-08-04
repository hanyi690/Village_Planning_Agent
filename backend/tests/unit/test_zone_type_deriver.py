import pytest

from app.tools.gis._generation.zone_type_deriver import derive_zone_types


@pytest.fixture(autouse=True)
def _legacy_switch(monkeypatch):
    """zone_type_deriver is fail-closed; these tests verify its pure logic
    under the explicit legacy switch (comparison testing only)."""
    monkeypatch.setenv("GIS_LEGACY_MAPPING", "1")


def test_derive_from_appendix5_1340_yields_forest():
    p = {"bsm": "A", "dlbm": "1340", "current_landuse_code": "1340"}
    out = derive_zone_types([p])
    assert out["A"]["zone_type"] == "农业用地"
    assert out["A"]["zone_type_sub"] == "商品林"
    assert out["A"]["encoding_provenance"] == "practical:appendix5"


def test_derive_from_dlbm_0301_yields_forest():
    p = {"bsm": "B", "dlbm": "0301"}
    out = derive_zone_types([p])
    assert out["B"]["zone_type"] == "农业用地"
    assert out["B"]["encoding_provenance"] == "derived:dlbm_to_ghytbm"


def test_missing_parcel_returns_none():
    p = {"bsm": "C", "dlbm": ""}
    out = derive_zone_types([p])
    assert out["C"]["zone_type"] is None
    assert out["C"]["encoding_provenance"] == "missing:upper_plan_transmission"


def test_derive_priority_current_over_dlbm():
    p = {"bsm": "P", "dlbm": "0301", "current_landuse_code": "1340"}
    out = derive_zone_types([p])
    assert out["P"]["ghytbm"] == "1340"
    assert out["P"]["zone_type_sub"] == "商品林"


def test_derive_uses_explicit_ghytbm():
    p = {"bsm": "G", "dlbm": "", "ghytbm": "2124"}
    out = derive_zone_types([p])
    assert out["G"]["ghytbm"] == "2124"
    assert out["G"]["zone_type"] == "产业用地"


def test_jintian_1340_path():
    """Jintian data: DLBM field actually holds 附录5 code 1340."""
    parcels = [
        {"bsm": f"J{i}", "dlbm": "1340", "current_landuse_code": "1340"}
        for i in range(3)
    ]
    out = derive_zone_types(parcels)
    assert all(v["zone_type"] == "农业用地" for v in out.values())
    assert all(v["encoding_provenance"] == "practical:appendix5" for v in out.values())