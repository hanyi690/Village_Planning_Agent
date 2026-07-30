"""Tests for L2 spatial relation builders with SemanticMemoryStore attributes."""
from rdflib import Literal, URIRef
from rdflib.namespace import RDF

from app.modules.kg.builder.base import PlanningKG
from app.modules.kg.ontology import PLN, EntityTypes, Relations
from app.modules.kg.builder.layer2 import add_parcel_relations
from app.modules.spatial_ops.geometry import ParcelRelations, TouchRelation, NearbyRelation


class TestParcelRelationsToMemoryStore:
    def test_touch_writes_relation_annotation(self):
        kg = PlanningKG("test")
        p1 = PLN["parcel_001"]
        p2 = PLN["parcel_002"]
        kg.g.add((p1, RDF.type, EntityTypes.Parcel))
        kg.g.add((p1, PLN.bsm, Literal("001")))
        kg.g.add((p2, RDF.type, EntityTypes.Parcel))
        kg.g.add((p2, PLN.bsm, Literal("002")))

        relations = ParcelRelations(
            touches=[TouchRelation(bsm_a="001", dlbm_a="0101", bsm_b="002", dlbm_b="0101", shared_boundary_length_m=45.2)],
            nearby=[],
            connected=[],
            parcel_road_intersects=[],
            parcel_water_touches=[],
        )
        add_parcel_relations(kg, relations)

        assert (p1, Relations.sfTouches, p2) in kg.g
        assert (p2, Relations.sfTouches, p1) in kg.g

        annotation = kg.memory.get_relation_semantics(str(p1), str(Relations.sfTouches), str(p2))
        assert annotation is not None
        assert annotation["quantitative_detail"]["shared_boundary_m"] == 45.2

    def test_no_shared_boundary_triple_in_rdf(self):
        kg = PlanningKG("test")
        p1 = PLN["parcel_001"]
        kg.g.add((p1, RDF.type, EntityTypes.Parcel))
        kg.g.add((p1, PLN.bsm, Literal("001")))
        p2 = PLN["parcel_002"]
        kg.g.add((p2, RDF.type, EntityTypes.Parcel))
        kg.g.add((p2, PLN.bsm, Literal("002")))

        relations = ParcelRelations(
            touches=[TouchRelation(bsm_a="001", dlbm_a="0101", bsm_b="002", dlbm_b="0101", shared_boundary_length_m=45.2)],
            nearby=[], connected=[], parcel_road_intersects=[], parcel_water_touches=[],
        )
        add_parcel_relations(kg, relations)

        assert (p1, PLN.shared_boundary_length, None) not in kg.g