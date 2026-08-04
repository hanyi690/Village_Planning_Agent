"""Integration tests for KG candidate BSM resolution (resolve_candidates).

Uses direct ingest (same as test_golden_kg_snapshot.py) to avoid
DataCatalog WMS/FMAP data source issue.

Run: cd F:/project/Village_Planning_Agent
     python -m pytest backend/tests/integration/test_spatial_ref_resolve.py -v --tb=short
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

_BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))
_PROJECT_ROOT = _BACKEND_DIR.parent
os.chdir(_PROJECT_ROOT)

_JINTIAN_DATA = _PROJECT_ROOT / "data" / "gis" / "jintian"


@pytest.fixture(scope="module")
def kg_main():
    from app.modules.data.ingest import ingest_current_landuse, ingest_feature
    from app.modules.schema.types.canonical import VillageBundle
    from app.modules.spatial_ops import build_constraint_index
    from app.modules.spatial_ops.geometry import compute_parcel_relations
    from app.modules.kg.builder import KGBuilder, PlanningKG

    bundle = VillageBundle(village_name="jintian")

    parcels, _ = ingest_current_landuse(str(_JINTIAN_DATA / "current" / "landuse.geojson"))
    for p in parcels:
        bundle.add(p)

    roads, _ = ingest_feature(str(_JINTIAN_DATA / "current" / "road.geojson"), "current_road")
    for r in roads:
        bundle.add(r)

    anns, _ = ingest_feature(str(_JINTIAN_DATA / "current" / "annotation.geojson"), "current_annotation")
    for a in anns:
        bundle.add(a)

    for feature_type, filename in [
        ("farmland_protection", "farmland_protection.geojson"),
        ("ecological_redline", "ecological_protection.geojson"),
        ("historical_protection", "historical_protection.geojson"),
    ]:
        path = _JINTIAN_DATA / "planned" / filename
        if path.exists():
            feats, _ = ingest_feature(str(path), feature_type)
            for f in feats:
                bundle.add(f)

    boundary, _ = ingest_feature(str(_JINTIAN_DATA / "current" / "boundary.geojson"), "admin_area")
    for b in boundary:
        bundle.add(b)

    assert bundle.parcel_count > 0, "No parcels loaded"
    rel = compute_parcel_relations(
        bundle.polygons.get("landuse_current"), roads=bundle.lines.get("roads_current"))
    ci = build_constraint_index(bundle)
    kg = KGBuilder(village_name="jintian").build_from_bundle(
        bundle=bundle, parcel_relations=rel, constraint_index=ci)
    return kg


class TestResolveCandidatesAttributive:
    def test_attributive_forest_returns_forest_bsms(self, kg_main):
        from app.modules.schema.contracts.spatial_reference_contracts import SpatialReferenceSpec
        from app.modules.kg.queries.spatial_ref import resolve_candidates
        spec = SpatialReferenceSpec(
            type="attributive",
            attr_filter={"dlbm_in": ["0301", "0302", "0307"]},
        )
        cs = resolve_candidates(kg_main, spec)
        assert isinstance(cs.bsms, list)
        assert len(cs.bsms) > 0, "Expected forest parcels in jintian"

    def test_attributive_empty_filter_returns_all_parcels(self, kg_main):
        from app.modules.schema.contracts.spatial_reference_contracts import SpatialReferenceSpec
        from app.modules.kg.queries.spatial_ref import resolve_candidates
        spec = SpatialReferenceSpec(type="attributive")
        cs = resolve_candidates(kg_main, spec)
        assert len(cs.bsms) == 660


class TestResolveCandidatesTopological:
    def test_topological_sfwithin_facility_returns_containing_parcels(self, kg_main):
        from app.modules.schema.contracts.spatial_reference_contracts import (
            SpatialReferenceSpec, RefObject,
        )
        from app.modules.kg.queries.spatial_ref import resolve_candidates
        spec = SpatialReferenceSpec(
            type="topological",
            reference=RefObject(kind="entity_type", filter={"rdf_type": "Facility"}),
            topo="sfWithin",
        )
        cs = resolve_candidates(kg_main, spec)
        assert len(cs.ref_bsms) > 0, "Expected facility BSMs as reference"
        assert len(cs.bsms) > 0, "Expected parcels containing facilities"


class TestResolveCandidatesEntityType:
    def test_entity_type_facility_by_label(self, kg_main):
        from app.modules.schema.contracts.spatial_reference_contracts import (
            SpatialReferenceSpec, RefObject,
        )
        from app.modules.kg.queries.spatial_ref import resolve_candidates
        spec = SpatialReferenceSpec(
            type="attributive",
            reference=RefObject(kind="entity_type", filter={"label_contains": "\u536b\u751f"}),
        )
        cs = resolve_candidates(kg_main, spec)
        assert len(cs.ref_bsms) > 0, "Expected at least one \u536b\u751f facility"


class TestResolveCandidatesLayerGroup:
    def test_layer_group_protection_returns_zone_bsms(self, kg_main):
        from app.modules.schema.contracts.spatial_reference_contracts import (
            SpatialReferenceSpec, RefObject,
        )
        from app.modules.kg.queries.spatial_ref import resolve_candidates
        spec = SpatialReferenceSpec(
            type="attributive",
            reference=RefObject(kind="layer_group", filter={"group": "protection"}),
        )
        cs = resolve_candidates(kg_main, spec)
        assert len(cs.ref_bsms) > 0, "Expected protection zone BSMs"