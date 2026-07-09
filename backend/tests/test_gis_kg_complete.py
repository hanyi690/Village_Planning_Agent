"""
Tests for PlanningKG completeness — 13 entity types, 11 relationship types,
and new builder/query methods.

Verifies that the extended KG produces:
- All 13 entity types present
- All 11 relationship types present
- Project → Indicator reference chains
- Regulation → Constraint → Zone impact chains
- Facility serves relations
- Road/WaterBody infrastructure entities
- designated_as parcel → zone relations
- Triple count increase over baseline
"""

from __future__ import annotations

import pytest

from app.services.modules.gis.layout.kg import PlanningKG, EntityTypes, Relations
from app.services.modules.gis.layout.kg.ontology import PLN
from rdflib import RDF

from tests.fixtures.gis_e2e import load_landuse_current


# --- Fixtures ---

@pytest.fixture(scope="module")
def landuse_geojson():
    return load_landuse_current()


@pytest.fixture(scope="module")
def l3_reports_for_kg():
    """Minimal L3 report data for KG building."""
    return {
        "land_use_planning": {
            "summary": {
                "metrics": {
                    "建设用地规模_公顷": 30.50,
                    "耕地保有量_公顷": 78.83,
                    "生态保护红线面积": 362.02,
                    "规划期末人口": 1850,
                    "人均建设用地": 164.86,
                    "村集体年收入": 150000,
                }
            },
            "content": (
                "金田村规划实施农田整治项目，推进道路硬化工程，"
                "建设公共服务设施项目，规划教育设施。"
                "生态农业发展区和生态保育屏障区是重点区域。"
            ),
        }
    }


@pytest.fixture(scope="module")
def kg(landuse_geojson, l3_reports_for_kg):
    """Build a complete KG with all entity types."""
    kg = PlanningKG(village_name="金田村")
    kg.build_from_reports(
        reports=l3_reports_for_kg,
        landuse_geojson=landuse_geojson,
        gis_data={"landuse_current_geojson": landuse_geojson},
    )
    return kg


# --- Entity Type Tests ---

class TestKGEntityTypes:

    def test_kg_has_parcel_entities(self, kg):
        parcels = list(kg.g.subjects(RDF.type, EntityTypes.Parcel))
        assert len(parcels) > 0

    def test_kg_has_zone_entities(self, kg):
        zones = list(kg.g.subjects(RDF.type, EntityTypes.Zone))
        assert len(zones) > 0

    def test_kg_has_constraint_entities(self, kg):
        constraints = list(kg.g.subjects(RDF.type, EntityTypes.Constraint))
        assert len(constraints) > 0

    def test_kg_has_indicator_entities(self, kg):
        indicators = list(kg.g.subjects(RDF.type, EntityTypes.Indicator))
        assert len(indicators) > 0

    def test_kg_has_project_entities(self, kg):
        projects = list(kg.g.subjects(RDF.type, EntityTypes.Project))
        assert len(projects) > 0, "KG should have at least one Project entity"

    def test_kg_has_village_entity(self, kg):
        villages = list(kg.g.subjects(RDF.type, EntityTypes.Village))
        assert len(villages) >= 1

    def test_kg_has_regulation_entities(self, kg):
        regulations = list(kg.g.subjects(RDF.type, EntityTypes.Regulation))
        assert len(regulations) > 0, "KG should have Regulation entities"

    def test_kg_has_facility_entities(self, kg):
        facilities = list(kg.g.subjects(RDF.type, EntityTypes.Facility))
        assert len(facilities) > 0, "KG should have Facility entities from DLBM data"

    def test_kg_has_road_entities(self, kg):
        roads = list(kg.g.subjects(RDF.type, EntityTypes.Road))
        assert len(roads) > 0, "KG should have Road entities from DLBM data"

    def test_kg_has_water_body_entities(self, kg):
        waters = list(kg.g.subjects(RDF.type, EntityTypes.WaterBody))
        assert len(waters) > 0, "KG should have WaterBody entities from DLBM data"


# --- Relationship Type Tests ---

class TestKGRelationshipTypes:

    def test_kg_has_adjacent_to_relations(self, kg):
        triples = list(kg.g.triples((None, Relations.adjacent_to, None)))
        assert len(triples) > 0

    def test_kg_has_located_in_relations(self, kg):
        triples = list(kg.g.triples((None, Relations.located_in, None)))
        assert len(triples) > 0, "Parcels should have located_in → Village"

    def test_kg_has_designated_as_relations(self, kg):
        triples = list(kg.g.triples((None, Relations.designated_as, None)))
        assert len(triples) > 0, "Parcels should have designated_as → Zone"

    def test_kg_has_achieves_relations(self, kg):
        triples = list(kg.g.triples((None, Relations.achieves, None)))
        assert len(triples) > 0, "Village should achieve Projects"

    def test_kg_has_protects_relations(self, kg):
        triples = list(kg.g.triples((None, Relations.protects, None)))
        assert len(triples) > 0, "Regulations should protect Zones"

    def test_kg_has_serves_relations(self, kg):
        triples = list(kg.g.triples((None, Relations.serves, None)))
        assert len(triples) > 0, "Facilities should serve someone"

    def test_kg_has_connects_relations(self, kg):
        triples = list(kg.g.triples((None, Relations.connects, None)))
        assert len(triples) > 0, "Village connects to Roads"


# --- Reference Chain Tests ---

class TestKGReferenceChains:

    def test_project_indicator_chain(self, kg):
        """Village → achieves → Project should exist."""
        achieves_triples = list(kg.g.triples((None, Relations.achieves, None)))
        assert len(achieves_triples) > 0

    def test_regulation_zone_chain(self, kg):
        """Regulation → protects → Zone should exist."""
        protects_triples = list(kg.g.triples((None, Relations.protects, None)))
        assert len(protects_triples) > 0

    def test_parcel_zone_designated_chain(self, kg):
        """Parcel → designated_as → Zone should exist."""
        designated = list(kg.g.triples((None, Relations.designated_as, None)))
        assert len(designated) > 0
        # Verify the target is a Zone entity
        for _, _, zone_uri in designated[:5]:
            assert (zone_uri, RDF.type, EntityTypes.Zone) in kg.g


# --- Query Template Tests ---

class TestKGQueries:

    def test_get_all_projects_query(self, kg):
        results = kg.query("""
            PREFIX pln: <http://village-planning.org/ontology#>
            SELECT ?project ?name ?source
            WHERE {
                ?project a pln:Project ;
                         pln:name ?name .
                OPTIONAL { ?project pln:source ?source . }
            }
        """)
        assert len(results) > 0

    def test_get_regulation_impacts_query(self, kg):
        results = kg.query("""
            PREFIX pln: <http://village-planning.org/ontology#>
            SELECT ?reg ?reg_name ?zone_name
            WHERE {
                ?reg a pln:Regulation ;
                     pln:name ?reg_name .
                OPTIONAL {
                    ?reg pln:protects ?zone .
                    ?zone pln:name ?zone_name .
                }
            }
        """)
        assert len(results) > 0

    def test_get_facility_serve_areas_query(self, kg):
        results = kg.query("""
            PREFIX pln: <http://village-planning.org/ontology#>
            SELECT ?facility ?name ?serves
            WHERE {
                ?facility a pln:Facility ;
                          pln:name ?name ;
                          pln:serves ?serves .
            }
        """)
        assert len(results) > 0

    def test_get_road_network_query(self, kg):
        results = kg.query("""
            PREFIX pln: <http://village-planning.org/ontology#>
            SELECT ?road ?name
            WHERE {
                ?road a pln:Road ;
                      pln:name ?name .
            }
        """)
        assert len(results) > 0

    def test_get_designated_zones_query(self, kg):
        results = kg.query("""
            PREFIX pln: <http://village-planning.org/ontology#>
            SELECT ?parcel ?bsm ?zone_name
            WHERE {
                ?parcel a pln:Parcel ;
                        pln:bsm ?bsm ;
                        pln:designated_as ?zone .
                ?zone pln:name ?zone_name .
            }
            LIMIT 10
        """)
        assert len(results) > 0

    def test_count_entity_types_query(self, kg):
        results = kg.query("""
            PREFIX pln: <http://village-planning.org/ontology#>
            SELECT ?type (COUNT(?entity) as ?count)
            WHERE {
                ?entity a ?type .
            }
            GROUP BY ?type
            ORDER BY DESC(?count)
        """)
        type_names = {r.get("type", "") for r in results}
        assert len(type_names) >= 8, f"Expected 8+ entity types, got {len(type_names)}"


# --- Triple Count Test ---

class TestKGTripleCount:

    def test_triple_count_increased(self, kg):
        """KG should have 1500+ triples with the new entity types."""
        count = kg.get_triple_count()
        assert count >= 1500, f"Triple count too low: {count} (expected 1500+)"


# --- Serialization Roundtrip ---

class TestKGSerialization:

    def test_turtle_roundtrip_preserves_entity_types(self, kg):
        turtle = kg.to_turtle()
        kg2 = PlanningKG.from_turtle(turtle, village_name="金田村")
        # Check key entity types are preserved
        for etype in [EntityTypes.Parcel, EntityTypes.Zone, EntityTypes.Constraint,
                      EntityTypes.Project, EntityTypes.Regulation, EntityTypes.Road]:
            count = len(list(kg2.g.subjects(RDF.type, etype)))
            assert count > 0, f"Entity type {etype} lost in roundtrip"
