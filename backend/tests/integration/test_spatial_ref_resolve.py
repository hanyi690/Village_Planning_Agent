"""Integration tests for KG candidate BSM resolution (resolve_candidates).

Uses the same jintian data fixtures as test_kg_jintian_e2e.py.
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


@pytest.fixture(scope="module")
def kg_main():
    from app.modules.data import DataCatalog
    from app.modules.spatial_ops import build_constraint_index
    from app.modules.spatial_ops.geometry import compute_parcel_relations
    from app.modules.kg.builder import PlanningKG
    catalog = DataCatalog()
    bundle = catalog.load_village_bundle("jintian")
    rel = compute_parcel_relations(
        bundle.polygons.landuse_current, roads=bundle.lines.roads_current)
    ci = build_constraint_index(bundle)
    kg = PlanningKG(village_name="jintian")
    kg.build_from_bundle(bundle=bundle, parcel_relations=rel, constraint_index=ci)
    return kg


class TestResolveCandidatesAttributive:
    def test_attributive_forest_returns_forest_bsms(self, kg_main):
        from app.modules.schema.contracts.spatial_ref_contracts import (
            SpatialReferenceSpec,
        )
        from app.modules.kg.queries.spatial_ref import resolve_candidates
        spec = SpatialReferenceSpec(
            type="attributive",
            attr_filter={"dlbm_in": ["0301", "0302", "0307"]},
        )
        cs = resolve_candidates(kg_main, spec)
        assert isinstance(cs.bsms, list)
        assert len(cs.bsms) > 0, "Expected forest parcels in jintian"

    def test_attributive_empty_filter_returns_all_parcels(self, kg_main):
        from app.modules.schema.contracts.spatial_ref_contracts import (
            SpatialReferenceSpec,
        )
        from app.modules.kg.queries.spatial_ref import resolve_candidates
        spec = SpatialReferenceSpec(type="attributive")
        cs = resolve_candidates(kg_main, spec)
        assert len(cs.bsms) == 660


class TestResolveCandidatesTopological:
    def test_topological_sfwithin_facility_returns_containing_parcels(self, kg_main):
        from app.modules.schema.contracts.spatial_ref_contracts import (
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
        from app.modules.schema.contracts.spatial_ref_contracts import (
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
    def test_layer_group_water_returns_water_bsms(self, kg_main):
        from app.modules.schema.contracts.spatial_ref_contracts import (
            SpatialReferenceSpec, RefObject,
        )
        from app.modules.kg.queries.spatial_ref import resolve_candidates
        spec = SpatialReferenceSpec(
            type="attributive",
            reference=RefObject(kind="layer_group", filter={"group": "water"}),
        )
        cs = resolve_candidates(kg_main, spec)
        assert len(cs.ref_bsms) > 0, "Expected water body BSMs"