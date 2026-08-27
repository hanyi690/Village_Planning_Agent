"""Current grounding invariants for coordinate identity and evidence scoring."""

from __future__ import annotations

from types import SimpleNamespace

from rdflib import Graph, Literal, Namespace

PLN = Namespace("http://village-planning.org/ontology#")
RDF = Namespace("http://www.w3.org/1999/02/22-rdf-syntax-ns#")


def _kg_graph():
    graph = Graph()
    facility = PLN.facility_bsm_1
    graph.add((facility, RDF.type, PLN.Facility))
    graph.add((facility, PLN.name, Literal("祠堂")))
    graph.add((facility, PLN.bsm, Literal("bsm-100")))
    graph.add((facility, PLN.lon, Literal("113.100")))
    graph.add((facility, PLN.lat, Literal("23.100")))
    water = PLN.water_body_bsm_2
    graph.add((water, RDF.type, PLN.WaterBody))
    graph.add((water, PLN.name, Literal("石窟河")))
    graph.add((water, PLN.bsm, Literal("bsm-200")))
    graph.add((water, PLN.lon, Literal("113.200")))
    graph.add((water, PLN.lat, Literal("23.200")))
    road = PLN.road_bsm_3
    graph.add((road, RDF.type, PLN.Road))
    graph.add((road, PLN.name, Literal("122乡道")))
    cluster = PLN.residential_cluster_bsm_4
    graph.add((cluster, RDF.type, PLN.ResidentialCluster))
    graph.add((cluster, PLN.name, Literal("社前村")))
    graph.add((cluster, PLN.bsm, Literal("bsm-400")))
    graph.add((cluster, PLN.lon, Literal("113.400")))
    graph.add((cluster, PLN.lat, Literal("23.400")))
    admin = PLN.administrative_village_bsm_5
    graph.add((admin, RDF.type, PLN.AdministrativeVillage))
    graph.add((admin, PLN.name, Literal("金田村")))
    graph.add((admin, PLN.bsm, Literal("bsm-500")))
    graph.add((facility, PLN.serves, admin))
    return graph


def _kg():
    from app.infrastructure.kg.builder.base import PlanningKG

    kg = PlanningKG(village_name="金田村")
    for triple in _kg_graph():
        kg.g.add(triple)
    return kg


def _context(kg):
    from app.infrastructure.kg.gazetteer import build_gazetteer

    return SimpleNamespace(
        session_id="s-core",
        version=1,
        kg_version=1,
        gazetteer=build_gazetteer(kg, None, None),
        location_facts=[],
        kg=kg,
        workspace=SimpleNamespace(
            points={"annotations_current": [], "facilities_current": []},
            polygons={"landuse_current": []},
        ),
        current_parcels=lambda: [],
    )


def test_coordinate_identity_same_coordinate():
    from app.spatial.grounding.coordinate_identity import coordinate_key, same_coordinate

    assert same_coordinate("POINT(113.1 23.1)", "kg_wkt:POINT(113.1 23.1)")
    assert not same_coordinate("POINT(113.1 23.1)", "POINT(113.2 23.1)")
    assert coordinate_key("POINT(113.123456 23.123456)") == coordinate_key(
        "POINT(113.1234561 23.1234562)"
    )
    assert coordinate_key(None) == ""


def test_topology_evidence_matches_village_hint():
    from app.spatial.grounding.topology import topology_evidence_for

    kg = _kg()
    hits = topology_evidence_for(kg.g, str(PLN.facility_bsm_1), hints="位于金田村")
    assert any("serves" in hit and "金田村" in hit for hit in hits), hits


def test_evidence_scorer_relation_topology_real_check():
    from app.contracts.ports.place_resolution_contracts import PlaceEvidenceEntry
    from app.evidence.index.evidence_scorer import score_candidate, total

    kg = _kg()
    entry = PlaceEvidenceEntry(
        canonical_name="祠堂",
        entity_refs=[str(PLN.facility_bsm_1)],
        entity_types=["facility"],
        role="facility",
        source_bsms=["bsm-100"],
        geometry_ref="POINT(113.1 23.1)",
        relation_refs=[],
    )
    evidence = score_candidate(
        "祠堂",
        entry,
        role="facility",
        hints="位于金田村",
        context=SimpleNamespace(kg=kg),
    )
    assert evidence["relation_topology"] == 0.5
    assert total(evidence) > 0.0


def test_evidence_index_coordinate_merge_same_entity():
    from app.evidence.index.place_evidence_index import PlaceEvidenceIndex

    kg = _kg()
    index = PlaceEvidenceIndex.build(_context(kg))
    by_name = {entry.canonical_name: entry for entry in index.entries}
    assert "祠堂" in by_name
