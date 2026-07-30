"""L4 provenance chain tests - EXECUTE_KG_UTILIZATION_DESIGN §3.

Verifies apply_planned_state writes the full 5-predicate provenance:
  pln:derived_from, pln:source_spec, pln:decided_by, pln:operation, pln:area_change_ha

Run: cd F:/project/Village_Planning_Agent
     python -m pytest backend/tests/integration/test_l4_provenance.py -v --tb=short
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
    from app.modules.kg.builder import KGBuilder

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

    assert bundle.parcel_count > 0
    rel = compute_parcel_relations(
        bundle.polygons.get("landuse_current"), roads=bundle.lines.get("roads_current"))
    ci = build_constraint_index(bundle)
    kg = KGBuilder.build("jintian", bundle, parcel_relations=rel, constraint_index=ci)
    return kg


def test_l4_provenance_five_predicates(kg_main):
    from app.modules.kg.builder.layer4 import PlannedState, PlannedParcelEntry, apply_planned_state
    from rdflib import Namespace, RDF, URIRef
    PLN = Namespace("http://village-planning.org/ontology#")

    real_bsm = None
    for s, _, o in kg_main.g.triples((None, PLN.bsm, None)):
        if (s, RDF.type, PLN.Parcel) in kg_main.g:
            real_bsm = str(o)
            break
    assert real_bsm is not None

    kg_plan = kg_main.clone_static_layer()
    apply_planned_state(kg_plan, PlannedState(version="v1", parcels=[
        PlannedParcelEntry(
            bsm=f"{real_bsm}_prov",
            planning_land_use="2121",
            area_ha=0.5,
            derived_from_bsms=[real_bsm],
            source_spec="directional:east_of_village",
            decided_by="rule",
            operation="reclassify",
            area_change_ha=-2.3,
        ),
    ]))

    pp_rows = kg_plan.query(
        "PREFIX pln: <http://village-planning.org/ontology#> "
        'SELECT ?p WHERE { ?p a pln:PlannedParcel ; pln:in_version "v1" . }')
    assert len(pp_rows) == 1
    pp_uri = pp_rows[0]["p"]

    def _obj(pred_uri):
        for _, _, o in kg_plan.g.triples((URIRef(pp_uri), pred_uri, None)):
            return str(o)
        return None

    assert _obj(PLN.source_spec) == "directional:east_of_village"
    assert _obj(PLN.decided_by) == "rule"
    assert _obj(PLN.operation) == "reclassify"
    area_change_ha_val = _obj(PLN.area_change_ha)
    assert area_change_ha_val is not None
    assert float(area_change_ha_val) == -2.3


def test_l4_provenance_defaults_empty(kg_main):
    from app.modules.kg.builder.layer4 import PlannedState, PlannedParcelEntry, apply_planned_state
    kg_plan = kg_main.clone_static_layer()
    apply_planned_state(kg_plan, PlannedState(version="v1", parcels=[
        PlannedParcelEntry(bsm="NO_PROV", planning_land_use="0101"),
    ]))
    pp_rows = kg_plan.query(
        "PREFIX pln: <http://village-planning.org/ontology#> "
        'SELECT ?p WHERE { ?p a pln:PlannedParcel ; pln:in_version "v1" . }')
    pp_uri = pp_rows[0]["p"]
    from rdflib import Namespace
    PLN = Namespace("http://village-planning.org/ontology#")
    assert len(list(kg_plan.g.triples((pp_uri, PLN.source_spec, None)))) == 0
    assert len(list(kg_plan.g.triples((pp_uri, PLN.decided_by, None)))) == 0


def test_l4_provenance_spquery(kg_main):
    from app.modules.kg.builder.layer4 import PlannedState, PlannedParcelEntry, apply_planned_state
    kg_plan = kg_main.clone_static_layer()
    apply_planned_state(kg_plan, PlannedState(version="v1", parcels=[
        PlannedParcelEntry(
            bsm="SPQ1", planning_land_use="2121",
            source_spec="attributive:all_forest",
            decided_by="llm", operation="new", area_change_ha=1.5,
        ),
    ]))
    rows = kg_plan.query(
        "PREFIX pln: <http://village-planning.org/ontology#> "
        "SELECT ?p ?spec ?by ?op ?chg WHERE { "
        "?p a pln:PlannedParcel ; pln:source_spec ?spec ; "
        "pln:decided_by ?by ; pln:operation ?op ; pln:area_change_ha ?chg . }")
    assert len(rows) == 1
    assert rows[0]["spec"] == "attributive:all_forest"
    assert rows[0]["by"] == "llm"
    assert rows[0]["op"] == "new"
    assert float(rows[0]["chg"]) == 1.5