"""Prohibited-construction constraint derivation tests.

Pins the MVP "1 禁止建设区" behavior: farmland_protection + ecological_redline
constraint polygons must be indexed by build_constraint_index and their
overlapping candidates hard-filtered by apply_hard_filters.
"""

import json
from pathlib import Path

from app.modules.schema.types.canonical import VillageBundle
from app.modules.schema.types.spatial_types import (
    EcologicalRedline,
    FarmlandProtection,
)
from app.modules.spatial_ops.index.bridge import (
    ConstraintIndex,
    build_constraint_index,
)
from app.modules.spatial_ops.selection.selection import (
    CandidateParcel,
    _PROHIBITED_CONSTRAINTS,
    apply_hard_filters,
)

_POLY_FARM = {
    "type": "Polygon",
    "coordinates": [[[0.0, 0.0], [0.0, 0.01], [0.01, 0.01], [0.01, 0.0], [0.0, 0.0]]],
}
_POLY_ECO = {
    "type": "Polygon",
    "coordinates": [[[0.02, 0.02], [0.02, 0.03], [0.03, 0.03], [0.03, 0.02], [0.02, 0.02]]],
}
_POLY_OUT = {
    "type": "Polygon",
    "coordinates": [[[1.0, 1.0], [1.0, 1.01], [1.01, 1.01], [1.01, 1.0], [1.0, 1.0]]],
}

_FIXTURE_GIS = (
    Path(__file__).resolve().parents[2] / "fixtures" / "mvp_village" / "gis"
)


def _constraint_bundle() -> VillageBundle:
    bundle = VillageBundle(village_name="test")
    bundle.polygons.set("farmland_protection", [
        FarmlandProtection(bsm="F1", geometry=_POLY_FARM),
    ])
    bundle.polygons.set("ecological_redline", [
        EcologicalRedline(bsm="E1", geometry=_POLY_ECO),
    ])
    return bundle


def _candidate(bsm: str, geometry: dict) -> CandidateParcel:
    return CandidateParcel(bsm=bsm, geometry=geometry, dlmc="空闲宅基地", area_ha=0.5)


def test_prohibited_constraints_contains_required_types():
    assert "farmland_protection" in _PROHIBITED_CONSTRAINTS
    assert "ecological_redline" in _PROHIBITED_CONSTRAINTS


def test_build_constraint_index_populated():
    idx = build_constraint_index(_constraint_bundle())
    assert idx is not None
    assert isinstance(idx, ConstraintIndex)


def test_apply_hard_filters_rejects_prohibited_zone():
    idx = build_constraint_index(_constraint_bundle())
    inside = _candidate("INSIDE", _POLY_ECO)
    outside = _candidate("OUTSIDE", _POLY_OUT)

    survivors, rejected = apply_hard_filters([inside, outside], constraint_index=idx)

    assert [s.bsm for s in survivors] == ["OUTSIDE"]
    assert len(rejected) == 1
    assert rejected[0].bsm == "INSIDE"
    assert any("constraint:ecological_redline" in d for d in rejected[0].detail)


def test_merge_ecological_protection_routes_to_redline_group():
    from app.modules.data.catalog.catalog import _merge_geojson_into_bundle

    geojson = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"OBJECTID": 1, "区县": "平远县"},
                "geometry": _POLY_ECO,
            },
            {
                "type": "Feature",
                "properties": {"OBJECTID": 2, "区县": "平远县"},
                "geometry": _POLY_FARM,
            },
        ],
    }
    bundle = VillageBundle(village_name="test")

    merged = _merge_geojson_into_bundle(bundle, "ecological_protection", geojson)

    assert merged == 2
    redline = bundle.polygons.get("ecological_redline")
    assert len(redline) == 2
    assert all(f.layer_type == "ecological_redline" for f in redline)
    assert bundle.polygons.get("upload_ecological_protection") == []


def test_merge_farmland_protection_routes_to_group():
    from app.modules.data.catalog.catalog import _merge_geojson_into_bundle

    geojson = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"BSM": "1", "XZQHDM": "441426110000"},
                "geometry": _POLY_FARM,
            }
        ],
    }
    bundle = VillageBundle(village_name="test")

    merged = _merge_geojson_into_bundle(bundle, "farmland_protection", geojson)

    assert merged == 1
    farmland = bundle.polygons.get("farmland_protection")
    assert len(farmland) == 1
    assert farmland[0].layer_type == "farmland_protection"


def test_mvp_fixture_ecological_protection_feature_count():
    from app.modules.data.catalog.catalog import _merge_geojson_into_bundle

    path = _FIXTURE_GIS / "ecological_protection.geojson"
    geojson = json.loads(path.read_text(encoding="utf-8"))
    bundle = VillageBundle(village_name="jintian")

    merged = _merge_geojson_into_bundle(bundle, "ecological_protection", geojson)

    assert merged == 5
    assert len(bundle.polygons.get("ecological_redline")) == 5


def test_mvp_fixture_farmland_protection_feature_count():
    from app.modules.data.catalog.catalog import _merge_geojson_into_bundle

    path = _FIXTURE_GIS / "farmland_protection.geojson"
    geojson = json.loads(path.read_text(encoding="utf-8"))
    bundle = VillageBundle(village_name="jintian")

    merged = _merge_geojson_into_bundle(bundle, "farmland_protection", geojson)

    assert merged == 88
    assert len(bundle.polygons.get("farmland_protection")) == 88
