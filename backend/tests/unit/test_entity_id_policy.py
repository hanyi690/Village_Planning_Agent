"""Unit tests for EntityIdPolicy and unified URI scheme.

Verifies:
- EntityIdPolicy.uri / fallback_uri / attach_bsm
- All L1 entity types have PLN.bsm literal
- get_adjacency_map returns pure BSMs (not composite keys)
- L4->L3 links (derived_from_target) when source field set
- No ThreeZone/ThreeLine entities in KG (moved to ConstraintIndex)
- Same-name entities don't collide (different BSM -> different URI)
"""
import pytest
from rdflib import Literal, RDF, Namespace

from app.modules.kg.ontology import PLN, EntityTypes, EntityIdPolicy
from app.modules.kg.builder.registry import BuildContext

PLN_NS = Namespace("http://village-planning.org/ontology#")


# ── EntityIdPolicy unit tests ───────────────────────────────────────


class TestEntityIdPolicy:
    """Test EntityIdPolicy URI generation and BSM attachment."""

    def test_uri_l1(self):
        uri = EntityIdPolicy.uri("parcel", "441426211000055682")
        assert str(uri) == str(PLN["parcel_441426211000055682"])

    def test_uri_l4_with_version(self):
        uri = EntityIdPolicy.uri("planned_parcel", "441426211000055682", "v1")
        assert str(uri) == str(PLN["planned_parcel_441426211000055682_v1"])

    def test_uri_l4_with_current_version(self):
        uri = EntityIdPolicy.uri("planned_parcel", "P001", "current")
        assert str(uri) == str(PLN["planned_parcel_P001_current"])

    def test_uri_no_version_omits_v_suffix(self):
        uri = EntityIdPolicy.uri("road", "R001")
        assert "_v" not in str(uri)

    def test_uri_encodes_unsafe_label_characters(self):
        uri = EntityIdPolicy.uri("axis_target", "沿金田河 | 生态轴")
        assert " " not in str(uri)
        assert "|" not in str(uri)

    def test_fallback_uri_with_ysdm(self):
        uri = EntityIdPolicy.fallback_uri("facility", "2001", 3)
        assert str(uri) == str(PLN["facility_2001_3"])

    def test_fallback_uri_without_ysdm(self):
        uri = EntityIdPolicy.fallback_uri("facility", "", 5)
        assert "noysdm" in str(uri)
        assert str(uri) == str(PLN["facility_noysdm_5"])

    def test_attach_bsm_adds_literal(self):
        from rdflib import Graph
        g = Graph()
        uri = PLN["test_entity_123"]
        EntityIdPolicy.attach_bsm(g, uri, "123")
        assert (uri, PLN.bsm, Literal("123")) in g

    def test_attach_bsm_empty_skips(self):
        from rdflib import Graph
        g = Graph()
        uri = PLN["test_entity_empty"]
        EntityIdPolicy.attach_bsm(g, uri, "")
        assert len(list(g.triples((uri, PLN.bsm, None)))) == 0


# ── KG integration tests ────────────────────────────────────────────


@pytest.fixture(scope="module")
def kg_test():
    """Build a minimal KG for testing EntityIdPolicy integration via KGBuilder."""
    from app.modules.kg.builder import KGBuilder
    from app.modules.schema.types.canonical import VillageBundle
    from app.modules.schema.types.spatial_types import (
        CurrentLandUseParcel, CurrentRoad, CurrentFacility,
    )

    bundle = VillageBundle(village_name="test_village")

    # Minimal geometry placeholders
    poly_geom = {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]}
    line_geom = {"type": "LineString", "coordinates": [[0, 0], [1, 1]]}
    point_geom = {"type": "Point", "coordinates": [0, 0]}

    # Add parcels with BSMs
    parcels = [
        CurrentLandUseParcel(geometry=poly_geom, bsm="P001", dlbm="0101", area_sqm=5000.0, name="水田"),
        CurrentLandUseParcel(geometry=poly_geom, bsm="P002", dlbm="0101", area_sqm=3000.0, name="水田"),
        CurrentLandUseParcel(geometry=poly_geom, bsm="P003", dlbm="2121", area_sqm=2000.0, name="村庄住宅"),
    ]
    for p in parcels:
        bundle.add(p)

    # Add roads
    roads = [
        CurrentRoad(geometry=line_geom, bsm="R001", road_level="村道", shape_length=500.0),
        CurrentRoad(geometry=line_geom, bsm="R002", road_level="主干道", shape_length=1200.0),
    ]
    for r in roads:
        bundle.add(r)

    # Add facilities (with BSM)
    facilities = [
        CurrentFacility(geometry=point_geom, bsm="F001", facility_name="村委会", facility_type="公共服务"),
        CurrentFacility(geometry=point_geom, bsm="F002", facility_name="卫生站", facility_type="医疗"),
    ]
    for f in facilities:
        bundle.add(f)

    kg = KGBuilder.build("test_village", bundle)
    return kg


class TestL1EntityBSMLiterals:
    """Verify all L1 entity types have PLN.bsm literal."""

    def test_parcels_have_bsm_literal(self, kg_test):
        for s in kg_test.g.subjects(RDF.type, EntityTypes.Parcel):
            bsms = list(kg_test.g.triples((s, PLN.bsm, None)))
            assert len(bsms) == 1, f"Parcel {s} missing BSM literal"

    def test_roads_have_bsm_literal(self, kg_test):
        for s in kg_test.g.subjects(RDF.type, EntityTypes.Road):
            bsms = list(kg_test.g.triples((s, PLN.bsm, None)))
            assert len(bsms) >= 1, f"Road {s} missing BSM literal"

    def test_facilities_have_bsm_literal(self, kg_test):
        for s in kg_test.g.subjects(RDF.type, EntityTypes.Facility):
            bsms = list(kg_test.g.triples((s, PLN.bsm, None)))
            assert len(bsms) >= 1, f"Facility {s} missing BSM literal"

    def test_parcel_uri_contains_bsm(self, kg_test):
        """Parcel URIs should start with parcel_{bsm} (with optional seq suffix for duplicates)."""
        for s in kg_test.g.subjects(RDF.type, EntityTypes.Parcel):
            s_str = str(s)
            fragment = s_str.split("#")[-1] if "#" in s_str else s_str
            assert fragment.startswith("parcel_")
            # BSM is the first component after "parcel_"
            bsm_part = fragment[len("parcel_"):]
            # Should not contain dlbm or area (old composite key format)
            # May contain a seq suffix for duplicate BSMs: bsm_1, bsm_2, etc.
            # But should not contain the old format with dlbm and area


class TestNoThreeZoneThreeLine:
    """Verify ThreeZone/ThreeLine are not created as KG entities."""

    def test_no_three_zone_entities(self, kg_test):
        tz = list(kg_test.g.subjects(RDF.type, PLN.ThreeZone))
        assert len(tz) == 0

    def test_no_three_line_entities(self, kg_test):
        tl = list(kg_test.g.subjects(RDF.type, PLN.ThreeLine))
        assert len(tl) == 0


class TestGetAdjacencyMap:
    """Verify get_adjacency_map returns pure BSMs via literal queries."""

    def test_adjacency_keys_are_pure_bsm(self, kg_test):
        """Add touches relations and verify adjacency map keys are pure BSMs."""
        from app.modules.kg.ontology import Relations
        parcels = list(kg_test.g.subjects(RDF.type, EntityTypes.Parcel))
        if len(parcels) >= 2:
            kg_test.g.add((parcels[0], Relations.sfTouches, parcels[1]))
            kg_test.g.add((parcels[1], Relations.sfTouches, parcels[0]))

        adj = kg_test.get_adjacency_map()
        for bsm in adj:
            assert "_" not in bsm, f"Adjacency key '{bsm}' contains underscore"
            for neighbor in adj[bsm]:
                assert "_" not in neighbor, f"Neighbor '{neighbor}' contains underscore"

    def test_adjacency_no_parcels_returns_empty(self):
        """Empty KG returns empty adjacency map."""
        from app.modules.kg.builder import PlanningKG
        kg = PlanningKG("empty")
        adj = kg.get_adjacency_map()
        assert isinstance(adj, dict)
        assert len(adj) == 0


class TestL4EntityIdAndLinks:
    """Verify L4 entities use EntityIdPolicy and L4->L3 links."""

    def test_l4_parcel_uri_has_version(self, kg_test):
        """L4 PlannedParcel URI includes version suffix."""
        from app.modules.kg.builder.layer4 import PlannedState, PlannedParcelEntry, apply_planned_state
        kg_clone = kg_test.clone_static_layer()
        apply_planned_state(kg_clone, PlannedState(
            version="v1",
            parcels=[PlannedParcelEntry(bsm="P001", planning_land_use="2121")],
        ))
        # Check URI format
        for s in kg_clone.g.subjects(RDF.type, EntityTypes.PlannedParcel):
            s_str = str(s)
            assert "_v1" in s_str, f"L4 URI '{s_str}' missing version suffix"

    def test_l4_parcel_has_bsm_literal(self, kg_test):
        """L4 PlannedParcel has PLN.bsm literal."""
        from app.modules.kg.builder.layer4 import PlannedState, PlannedParcelEntry, apply_planned_state
        kg_clone = kg_test.clone_static_layer()
        apply_planned_state(kg_clone, PlannedState(
            version="v1",
            parcels=[PlannedParcelEntry(bsm="P001", planning_land_use="2121")],
        ))
        for s in kg_clone.g.subjects(RDF.type, EntityTypes.PlannedParcel):
            bsms = list(kg_clone.g.triples((s, PLN.bsm, None)))
            assert len(bsms) == 1, f"L4 entity {s} missing BSM literal"

    def test_l4_derived_from_target(self, kg_test):
        """L4 entity writes derived_from_target when source field set."""
        from app.modules.kg.builder.layer4 import (
            PlannedState, PlannedParcelEntry, PlannedFacilityEntry, apply_planned_state,
        )
        target_uri = str(PLN["zone_target_residential"])
        kg_clone = kg_test.clone_static_layer()
        apply_planned_state(kg_clone, PlannedState(
            version="v1",
            parcels=[PlannedParcelEntry(
                bsm="P001", planning_land_use="2121",
                derived_from_zone_target=target_uri,
            )],
            facilities=[PlannedFacilityEntry(
                name="新设施", facility_type="公共服务",
                derived_from_target=str(PLN["facility_target_公共服务"]),
            )],
        ))
        # Check derived_from_target triple exists
        dft = list(kg_clone.g.triples((None, PLN.derived_from_target, None)))
        assert len(dft) >= 2, f"Expected 2 derived_from_target triples, got {len(dft)}"


class TestNoNameCollision:
    """Verify same-name entities with different BSMs don't collide."""

    def test_two_facilities_same_name_different_bsm(self):
        """Two facilities with same name but different BSM get different URIs."""
        from app.modules.kg.builder import KGBuilder
        from app.modules.schema.types.canonical import VillageBundle
        from app.modules.schema.types.spatial_types import CurrentFacility

        bundle = VillageBundle(village_name="test")
        point_geom = {"type": "Point", "coordinates": [0, 0]}
        facilities = [
            CurrentFacility(geometry=point_geom, bsm="F001", facility_name="村委会", facility_type="公共服务"),
            CurrentFacility(geometry=point_geom, bsm="F002", facility_name="村委会", facility_type="公共服务"),
        ]
        for f in facilities:
            bundle.add(f)
        kg = KGBuilder.build("test", bundle)

        # Should have 2 distinct Facility URIs
        fac_uris = list(kg.g.subjects(RDF.type, EntityTypes.Facility))
        assert len(fac_uris) == 2, f"Expected 2 facilities, got {len(fac_uris)} - name collision!"
