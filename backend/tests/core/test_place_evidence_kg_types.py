"""Tests for KG multi-type entity registration in PlaceEvidenceIndex.

Covers design 12: named facilities / roads / water bodies / admin villages /
place refs (not only residential clusters) become locatable index entries
with BSM, geometry ref and relation refs.
"""
from __future__ import annotations

from types import SimpleNamespace

from rdflib import Graph, Literal, Namespace, URIRef

from app.evidence.index.place_evidence_index import PlaceEvidenceIndex

PLN = Namespace("http://village-planning.org/ontology#")
GEO = Namespace("http://www.opengis.net/ont/geosparql#")
RDF = Namespace("http://www.w3.org/1999/02/22-rdf-syntax-ns#")


def _kg_graph():
    g = Graph()
    # facility with BSM + name + coords + facility_type alias
    fac = PLN.facility_bsm_1
    g.add((fac, RDF.type, PLN.Facility))
    g.add((fac, PLN.name, Literal("祠堂")))
    g.add((fac, PLN.facility_type, Literal("文化设施")))
    g.add((fac, PLN.bsm, Literal("bsm-100")))
    g.add((fac, PLN.lon, Literal("113.100")))
    g.add((fac, PLN.lat, Literal("23.100")))
    # water body with name + bsm
    water = PLN.water_body_bsm_2
    g.add((water, RDF.type, PLN.WaterBody))
    g.add((water, PLN.name, Literal("石窟河")))
    g.add((water, PLN.bsm, Literal("bsm-200")))
    # road with name but no bsm
    road = PLN.road_bsm_3
    g.add((road, RDF.type, PLN.Road))
    g.add((road, PLN.name, Literal("122乡道")))
    # residential cluster
    cluster = PLN.residential_cluster_bsm_4
    g.add((cluster, RDF.type, PLN.ResidentialCluster))
    g.add((cluster, PLN.name, Literal("园寨村")))
    g.add((cluster, PLN.bsm, Literal("bsm-400")))
    # admin village with relation to facility (serves)
    admin = PLN.administrative_village_bsm_5
    g.add((admin, RDF.type, PLN.AdministrativeVillage))
    g.add((admin, PLN.name, Literal("金田村")))
    g.add((admin, PLN.bsm, Literal("bsm-500")))
    g.add((fac, PLN.serves, admin))
    return g


def _context(kg):
    return SimpleNamespace(
        session_id="s-kg",
        version=1,
        kg_version=1,
        gazetteer=None,
        location_facts=[],
        kg=kg,
        workspace=SimpleNamespace(
            points={"annotations_current": []},
            polygons={"landuse_current": []},
        ),
        current_parcels=lambda: [],
    )


def test_kg_multi_type_entities_are_registered():
    index = PlaceEvidenceIndex.build(_context(_kg_graph()))
    by_name = {e.canonical_name: e for e in index.entries}
    assert "祠堂" in by_name
    assert "石窟河" in by_name
    assert "122乡道" in by_name
    assert "园寨村" in by_name
    assert "金田村" in by_name

    fac = by_name["祠堂"]
    assert fac.role == "facility"
    assert fac.source_bsms == ["bsm-100"]
    assert fac.geometry_ref == "POINT(113.1 23.1)"
    assert fac.confidence >= 0.6
    assert any("serves" in r for r in fac.relation_refs)

    water = by_name["石窟河"]
    assert water.role == "water"
    assert water.source_bsms == ["bsm-200"]

    road = by_name["122乡道"]
    assert road.role == "road"
    assert road.source_bsms == []

    admin = by_name["金田村"]
    assert admin.role == "village"


def test_kg_entity_resolves_via_mention():
    index = PlaceEvidenceIndex.build(_context(_kg_graph()))
    result = index.resolve_mention("村内祠堂修缮保护")
    assert result.status == "resolved"
    assert result.selected_entity_ref == str(PLN.facility_bsm_1)
    assert result.candidates[0].source_bsms == ["bsm-100"]