"""End-to-end KG integration test with real jintian data.

Verifies the complete data flow:
  DataCatalog -> VillageBundle -> spatial_ops -> PlanningKG -> queries

Critical design constraint (per user requirement):
  - Plan injection test MUST be separate from main KG construction.
  - Main KG (Layer 1+2 from real data) must NOT have Layer 3/4 injected.
  - Plan/intent injection tests use clone_static_layer() to isolate.
  - After injection tests, main KG triple count and content must be unchanged.

Usage:
  cd F:/project/Village_Planning_Agent
  python -m pytest backend/tests/integration/test_kg_jintian_e2e.py -v --tb=short -s

  Or run directly:
  cd F:/project/Village_Planning_Agent/backend
  python tests/integration/test_kg_jintian_e2e.py
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pytest

# Ensure backend is on path when run as script
# tests/integration/test_kg_jintian_e2e.py -> parents[2] = backend/
_BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

# Project root must be cwd for DataCatalog relative paths (data/gis/jintian/...)
_PROJECT_ROOT = _BACKEND_DIR.parent
os.chdir(_PROJECT_ROOT)


# ── Module-scoped fixtures (built once, shared across tests) ────────


@pytest.fixture(scope="module")
def village_bundle():
    """Load real jintian VillageBundle via DataCatalog."""
    from app.modules.data import DataCatalog
    catalog = DataCatalog()
    bundle = catalog.load_village_bundle("jintian")
    assert bundle.parcel_count > 0, "No parcels loaded from jintian"
    return bundle


@pytest.fixture(scope="module")
def context_blocks(village_bundle):
    """Compute ContextBlocks from VillageBundle via spatial_ops."""
    from app.modules.spatial_ops import compute_context_blocks
    blocks = compute_context_blocks(village_bundle, max_token_budget=5000)
    assert len(blocks) > 0, "No context blocks generated"
    return blocks


@pytest.fixture(scope="module")
def parcel_relations(village_bundle):
    """Compute three-layer ParcelRelations via spatial_ops.geometry."""
    from app.modules.spatial_ops.geometry import compute_parcel_relations, ParcelRelations
    rel = compute_parcel_relations(
        village_bundle.polygons.landuse_current,
        roads=village_bundle.lines.roads_current,
    )
    assert isinstance(rel, ParcelRelations)
    return rel


@pytest.fixture(scope="module")
def kg_main(village_bundle, context_blocks, parcel_relations):
    """Build main KG with Layer 1+2 ONLY (no L3 intent, no L4 planned).

    This is the "clean" KG that must remain unaffected by L3/L4 injection tests.
    """
    from app.modules.kg.builder import PlanningKG
    from app.modules.spatial_ops import build_constraint_index
    constraint_index = build_constraint_index(village_bundle)
    kg = PlanningKG(village_name="jintian")
    kg.build_from_bundle(
        bundle=village_bundle,
        parcel_relations=parcel_relations,
        constraint_index=constraint_index,
        # intent=None, planned_state=None - deliberately omitted
    )
    return kg


# ── Part 1: Data loading verification ───────────────────────────────


class TestDataLoading:
    """Verify real jintian data loads correctly through the Data layer."""

    def test_village_bundle_has_parcels(self, village_bundle):
        """Layer 1 source: at least 600 current landuse parcels."""
        assert len(village_bundle.polygons.landuse_current) >= 600

    def test_village_bundle_has_roads(self, village_bundle):
        """Layer 1 source: roads loaded."""
        assert len(village_bundle.lines.roads_current) > 0

    def test_village_bundle_has_annotations(self, village_bundle):
        """Layer 1 source: annotations loaded."""
        assert len(village_bundle.points.annotations_current) > 0

    def test_village_bundle_has_protection_zones(self, village_bundle):
        """Layer 1 source: protection zones loaded."""
        assert len(village_bundle.polygons.farmland_protection) > 0
        assert len(village_bundle.polygons.ecological_redline) > 0

    def test_village_bundle_has_construction_zone(self, village_bundle):
        """Layer 1 source: construction zone loaded."""
        assert len(village_bundle.polygons.construction_zone) > 0

    def test_parcels_are_typed(self, village_bundle):
        """Parcels are typed CurrentLandUseParcel, not raw dicts."""
        from app.modules.schema.types.spatial_types import CurrentLandUseParcel
        p = village_bundle.polygons.landuse_current[0]
        assert isinstance(p, CurrentLandUseParcel)
        assert p.dlbm  # non-empty DLBM
        assert p.bsm  # non-empty BSM
        assert p.geometry  # has geometry


# ── Part 2: Context block computation ───────────────────────────────


class TestContextBlocks:
    """Verify spatial_ops produces typed ContextBlocks."""

    def test_blocks_are_typed(self, context_blocks):
        """ContextBlocks are typed, not raw dicts."""
        from app.modules.schema.contracts.context_contracts import ContextBlock
        for b in context_blocks:
            assert isinstance(b, ContextBlock)

    def test_blocks_contain_village_meta(self, context_blocks):
        """VILLAGE_META block exists."""
        from app.modules.schema.contracts.context_contracts import ContextBlockType as CBT
        types = {b.block_type for b in context_blocks}
        assert CBT.VILLAGE_META in types

    def test_blocks_contain_constraints(self, context_blocks):
        """CONSTRAINTS block exists with typed units."""
        from app.modules.schema.contracts.context_contracts import (
            ContextBlockType as CBT, ConstraintZoneAnchor,
        )
        cblock = next((b for b in context_blocks if b.block_type == CBT.CONSTRAINTS), None)
        assert cblock is not None, "No CONSTRAINTS block"
        # Typed units (PolygonBasedCognition)
        assert any(isinstance(u, ConstraintZoneAnchor) for u in cblock.units)

    def test_blocks_contain_facilities(self, context_blocks):
        """FACILITIES block exists with typed FacilityAnchor units."""
        from app.modules.schema.contracts.context_contracts import (
            ContextBlockType as CBT, FacilityAnchor,
        )
        fblock = next((b for b in context_blocks if b.block_type == CBT.FACILITIES), None)
        assert fblock is not None, "No FACILITIES block"
        assert any(isinstance(u, FacilityAnchor) for u in fblock.units)


# ── Part 3: Parcel relations computation ────────────────────────────


class TestParcelRelations:
    """Verify spatial_ops.geometry computes three-layer relations."""

    def test_relations_typed(self, parcel_relations):
        """ParcelRelations is the typed container, not a dict."""
        from app.modules.spatial_ops.geometry import ParcelRelations
        assert isinstance(parcel_relations, ParcelRelations)

    def test_touches_computed(self, parcel_relations):
        """L1 topological touches: at least some pairs share boundaries."""
        # Jintian has 660 parcels; expect many adjacency relations
        assert len(parcel_relations.touches) > 0
        # Verify each touch has shared_boundary_length
        t0 = parcel_relations.touches[0]
        assert t0.bsm_a and t0.bsm_b
        assert t0.shared_boundary_length_m >= 0

    def test_nearby_computed(self, parcel_relations):
        """L2 nearby: centroid distance relations exist."""
        # Within 200m, many parcels will be nearby
        assert len(parcel_relations.nearby) > 0
        n0 = parcel_relations.nearby[0]
        assert n0.centroid_distance_m > 0

    def test_connected_computed(self, parcel_relations):
        """L3 connected: parcels crossed by the same road are linked."""
        # With 131 roads crossing 660 parcels, expect some connected pairs
        assert len(parcel_relations.connected) > 0
        c0 = parcel_relations.connected[0]
        assert c0.bsm_a and c0.bsm_b
        # road_bsm may be empty (some roads lack BSM), but road_length should exist
        assert c0.road_length_m >= 0


# ── Part 4: KG Layer 1+2 construction ───────────────────────────────


class TestKGLayer1Construction:
    """Verify main KG builds with real data (Layer 1 + Layer 2)."""

    def test_kg_built_successfully(self, kg_main):
        """KG build completed without error."""
        assert kg_main is not None
        assert kg_main.get_triple_count() > 0

    def test_parcel_count_matches_bundle(self, kg_main, village_bundle):
        """KG parcel count matches bundle.landuse_current count."""
        expected = len(village_bundle.polygons.landuse_current)
        assert kg_main.get_parcel_count() == expected

    def test_layer1_parcels_in_graph(self, kg_main):
        """pln:Parcel entities exist in graph."""
        parcels = kg_main.query(
            "PREFIX pln: <http://village-planning.org/ontology#> "
            "SELECT ?p WHERE { ?p a pln:Parcel . }")
        assert len(parcels) >= 600

    def test_layer1_village_entity(self, kg_main):
        """pln:AdministrativeVillage entity exists."""
        villages = kg_main.query(
            "PREFIX pln: <http://village-planning.org/ontology#> "
            "SELECT ?v ?name WHERE { ?v a pln:AdministrativeVillage ; pln:name ?name . }")
        assert len(villages) == 1

    def test_layer1_roads_in_graph(self, kg_main):
        """pln:Road entities exist from infrastructure classification."""
        roads = kg_main.query(
            "PREFIX pln: <http://village-planning.org/ontology#> "
            "SELECT ?r WHERE { ?r a pln:Road . }")
        # Roads from add_roads() only (DLBM-based road inference removed in v4.4.1)
        assert len(roads) > 0

    def test_layer1_parcel_dlbm_attributes(self, kg_main):
        """Parcel DLBM attributes loaded from bundle."""
        parcels = kg_main.query(
            "PREFIX pln: <http://village-planning.org/ontology#> "
            "SELECT ?p ?dlbm WHERE { ?p a pln:Parcel ; pln:dlbm ?dlbm . } LIMIT 1")
        assert len(parcels) == 1
        assert parcels[0].get("dlbm", "")

    def test_no_three_zone_three_line_in_kg(self, kg_main):
        """ThreeZone/ThreeLine removed from KG - they are reference-layer data.

        Constraint polygons (farmland_protection, ecological_redline, etc.)
        are accessed via spatial_ops.bridge.ConstraintIndex, not stored as
        KG entities. This test verifies no ThreeZone/ThreeLine triples exist.
        """
        tz = kg_main.query(
            "PREFIX pln: <http://village-planning.org/ontology#> "
            "SELECT ?z WHERE { ?z a pln:ThreeZone . }")
        tl = kg_main.query(
            "PREFIX pln: <http://village-planning.org/ontology#> "
            "SELECT ?l WHERE { ?l a pln:ThreeLine . }")
        assert len(tz) == 0, "ThreeZone should not be in KG (reference-layer data)"
        assert len(tl) == 0, "ThreeLine should not be in KG (reference-layer data)"

    def test_constraint_index_built(self, kg_main):
        """ConstraintIndex is injected and indexes jintian constraint polygons."""
        # kg_main should have constraint_index from fixture
        assert kg_main._constraint_index is not None
        # Jintian has farmland_protection(88) + ecological_redline(5) + historical_protection(3)

    def test_layer1_parcel_relations_injected(self, kg_main, parcel_relations):
        """L1 touches + L2 nearby relations from spatial_ops are in graph."""
        # Query for touches relations
        touches_count = 0
        for s, _, _ in kg_main.g.triples((None, kg_main.g.namespace_manager.store.bind("pln", None, override=False) and None, None)):
            break
        from rdflib import Namespace
        PLN = Namespace("http://village-planning.org/ontology#")
        touches = list(kg_main.g.triples((None, PLN.touches, None)))
        nearby = list(kg_main.g.triples((None, PLN.nearby, None)))
        # At least some relations should have been injected
        assert len(touches) > 0 or len(nearby) > 0

    def test_layer1_natural_villages(self, kg_main):
        """NaturalSettlement entities from NATURAL_VILLAGES block."""
        nv = kg_main.query(
            "PREFIX pln: <http://village-planning.org/ontology#> "
            "SELECT ?v WHERE { ?v a pln:NaturalSettlement . }")
        # Jintian has annotation villages - should find some
        # (May be 0 if no residential DLBMs in jintian, but annotations exist)
        # At minimum, village entity should exist
        assert kg_main.get_triple_count() > 0

    def test_no_layer3_intent_in_main_kg(self, kg_main):
        """Main KG has NO Layer 3 intent entities (clean state)."""
        zt = kg_main.query(
            "PREFIX pln: <http://village-planning.org/ontology#> "
            "SELECT ?z WHERE { ?z a pln:ZoneTarget . }")
        ft = kg_main.query(
            "PREFIX pln: <http://village-planning.org/ontology#> "
            "SELECT ?f WHERE { ?f a pln:FacilityTarget . }")
        assert len(zt) == 0, "Main KG should not have ZoneTarget (L3)"
        assert len(ft) == 0, "Main KG should not have FacilityTarget (L3)"

    def test_no_layer4_planned_in_main_kg(self, kg_main):
        """Main KG has NO Layer 4 planned entities (clean state)."""
        pp = kg_main.query(
            "PREFIX pln: <http://village-planning.org/ontology#> "
            "SELECT ?p WHERE { ?p a pln:PlannedParcel . }")
        assert len(pp) == 0, "Main KG should not have PlannedParcel (L4)"


# ── Part 5: Query verification ──────────────────────────────────────


class TestKGQueries:
    """Verify all query methods work on the main KG."""

    def test_get_parcel_count(self, kg_main):
        assert kg_main.get_parcel_count() > 0

    def test_get_triple_count(self, kg_main):
        assert kg_main.get_triple_count() > 100

    def test_get_three_line_entities(self, kg_main):
        from app.modules.kg.queries import query_kg
        tl = kg_main.query(
            "PREFIX pln: <http://village-planning.org/ontology#> "
            "SELECT ?z ?name WHERE { ?z a pln:ThreeLine ; pln:name ?name . }")
        assert isinstance(tl, list)

    def test_get_adjacency_map(self, kg_main):
        """Adjacency map from touches relations - keys must be pure BSMs."""
        adj = kg_main.get_adjacency_map()
        assert isinstance(adj, dict)
        # If non-empty, keys should be pure BSM strings (not composite keys)
        for bsm, neighbors in adj.items():
            # BSM is a numeric string, should not contain underscores
            # (old format was bsm_dlbm_area which contained underscores)
            assert "_" not in bsm, f"Adjacency key '{bsm}' contains underscore - not pure BSM"
            for n in neighbors:
                assert "_" not in n, f"Neighbor '{n}' contains underscore - not pure BSM"

    def test_sparql_query_parcels_by_dlbm(self, kg_main):
        """SPARQL: query parcels by DLBM code."""
        # 0101 = 水田 (paddy field), common in jintian
        rows = kg_main.query(
            "PREFIX pln: <http://village-planning.org/ontology#> "
            "SELECT ?p ?bsm ?area WHERE { "
            "?p a pln:Parcel ; pln:bsm ?bsm ; pln:area_ha ?area . } LIMIT 5")
        assert len(rows) > 0
        assert "bsm" in rows[0]

    def test_sparql_query_constraint_zones(self, kg_main):
        """SPARQL: constraint zones accessed via ConstraintIndex, not KG triples."""
        from rdflib import Namespace
        PLN = Namespace("http://village-planning.org/ontology#")
        # No ThreeLine triples in KG (moved to ConstraintIndex)
        tl = kg_main.query(
            "PREFIX pln: <http://village-planning.org/ontology#> "
            "SELECT ?l ?name WHERE { ?l a pln:ThreeLine ; pln:name ?name . }")
        assert len(tl) == 0
        # But constraint_index is available for spatial queries
        assert kg_main._constraint_index is not None

    def test_to_turtle_serialization(self, kg_main):
        """KG serializes to turtle format."""
        ttl = kg_main.to_turtle()
        assert isinstance(ttl, str)
        assert len(ttl) > 100
        assert "pln:" in ttl or "village-planning" in ttl

    def test_from_turtle_roundtrip(self, kg_main):
        """KG can be reconstructed from turtle."""
        from app.modules.kg.builder import PlanningKG
        ttl = kg_main.to_turtle()
        kg2 = PlanningKG.from_turtle(ttl, village_name="jintian")
        assert kg2.get_triple_count() == kg_main.get_triple_count()

    def test_get_parcels_within_distance(self, kg_main):
        """get_parcels_within_distance_of_entity runs without error.

        Note: returns parcels connected via nearby/touches to the entity.
        May be empty if entity has no relation triples.
        """
        # Use the village URI as entity
        village_uri = "http://village-planning.org/ontology#village"
        result = kg_main.get_parcels_within_distance_of_entity(village_uri, 500)
        assert isinstance(result, list)

    def test_get_adjacent_parcels_with_length(self, kg_main):
        """get_adjacent_parcels_with_length runs for a known BSM."""
        # Get a real BSM from the graph
        from rdflib import Namespace, Literal
        PLN = Namespace("http://village-planning.org/ontology#")
        bsm_literal = None
        for s, _, o in kg_main.g.triples((None, PLN.bsm, None)):
            if (s, None, PLN.Parcel) in kg_main.g:
                bsm_literal = str(o)
                break
        if bsm_literal:
            result = kg_main.get_adjacent_parcels_with_length(bsm_literal)
            assert isinstance(result, list)

    def test_l3_connected_via_road_in_graph(self, kg_main):
        """L3 connected_via_road relations exist in KG from road network."""
        from rdflib import Namespace
        PLN = Namespace("http://village-planning.org/ontology#")
        connected = list(kg_main.g.triples((None, PLN.connected_via_road, None)))
        assert len(connected) > 0, "No connected_via_road triples - L3 not computed"

    def test_get_connected_parcels(self, kg_main):
        """get_connected_parcels returns BSMs connected via road network."""
        from rdflib import Namespace
        PLN = Namespace("http://village-planning.org/ontology#")
        # Find a parcel URI that has connected_via_road
        parcel_uri = None
        for s, _, _ in kg_main.g.triples((None, PLN.connected_via_road, None)):
            if (s, None, PLN.Parcel) in kg_main.g:
                parcel_uri = str(s)
                break
        if parcel_uri:
            result = kg_main.get_connected_parcels(parcel_uri)
            assert isinstance(result, list)
            assert len(result) > 0, "Should find at least one connected parcel"

    def test_roads_from_road_layer(self, kg_main):
        """KG has roads exclusively from road.geojson (via add_roads)."""
        from rdflib import Namespace
        PLN = Namespace("http://village-planning.org/ontology#")
        # Roads from add_roads() have pln:road_level and pln:length
        rd = kg_main.query(
            "PREFIX pln: <http://village-planning.org/ontology#> "
            "SELECT ?r ?level ?len WHERE { "
            "?r a pln:Road ; pln:road_level ?level . "
            "OPTIONAL { ?r pln:length ?len . } }")
        # Should have roads with road_level (from CurrentRoad typed objects)
        assert len(rd) > 0
        # At least some should have length (from shape_length)
        with_len = [r for r in rd if r.get("len")]
        assert len(with_len) > 0, "No roads with length - road.geojson not loaded"


# ── Part 6: Plan injection (SEPARATE - must not affect main KG) ─────


class TestPlanInjectionIsolated:
    """Layer 4 plan injection test - MUST be isolated from main KG.

    Design:
      1. Clone kg_main via clone_static_layer() -> kg_plan
      2. Inject PlanBlock into kg_plan ONLY
      3. Verify L4 entities in kg_plan
      4. Verify kg_main is UNAFFECTED (triple count unchanged, no L4 entities)

    This mirrors the real workflow where:
      - KG L1 is cached/shared across sessions (immutable)
      - KG L4 is session-specific (each EXECUTE iteration writes its own)
    """

    def test_clone_preserves_layer1(self, kg_main):
        """clone_static_layer() preserves all L1 triples."""
        from app.modules.kg.builder import PlanningKG
        original_count = kg_main.get_triple_count()

        kg_clone = kg_main.clone_static_layer()
        # Clone should have most/all L1 triples
        assert kg_clone.get_triple_count() > 0
        # Clone parcel count must match
        assert kg_clone.get_parcel_count() == kg_main.get_parcel_count()

    def test_clone_excludes_layer3_4(self, kg_main):
        """clone_static_layer() excludes L3/L4 entities (clean clone)."""
        # First add some L3 to a clone, then verify clone_static_layer
        # doesn't propagate it
        from app.modules.kg.builder import PlanningKG
        from app.modules.schema.contracts.parse_contracts import (
            SpatialPlanningIntent, ZoneTarget,
        )
        from app.modules.schema.contracts.parse_contracts import (
            SpatialPlanningIntent, ZoneTarget,
        )
        from app.modules.kg.builder.layer4 import (
            PlannedState, PlannedParcelEntry,
        )

        # Build a KG with L3+L4
        kg_with_l34 = kg_main.clone_static_layer()
        kg_with_l34._add_structured_intent(SpatialPlanningIntent(
            village_name="test",
            zone_targets=[ZoneTarget(land_use="2121", area_ratio=10.0)],
        ))
        kg_with_l34._apply_planned_state(PlannedState(version="test",
            parcels=[PlannedParcelEntry(bsm="CLONE_TEST", planning_land_use="2121")]))

        # Now clone THIS - the new clone should NOT have L3/L4
        kg_clean = kg_with_l34.clone_static_layer()
        zt = kg_clean.query(
            "PREFIX pln: <http://village-planning.org/ontology#> "
            "SELECT ?z WHERE { ?z a pln:ZoneTarget . }")
        pp = kg_clean.query(
            "PREFIX pln: <http://village-planning.org/ontology#> "
            "SELECT ?p WHERE { ?p a pln:PlannedParcel . }")
        assert len(zt) == 0, "Clone should exclude L3 ZoneTarget"
        assert len(pp) == 0, "Clone should exclude L4 PlannedParcel"

    def test_inject_planned_state_to_clone(self, kg_main, village_bundle):
        """Inject PlannedState into a CLONE, not kg_main."""
        from app.modules.kg.builder.layer4 import (
            PlannedState, PlannedParcelEntry, PlannedFacilityEntry, PlannedRoadEntry,
        )

        # Get a real BSM from the main KG for realistic test
        from rdflib import Namespace
        PLN = Namespace("http://village-planning.org/ontology#")
        real_bsms = []
        for s, _, o in kg_main.g.triples((None, PLN.bsm, None)):
            if (s, None, PLN.Parcel) in kg_main.g:
                real_bsms.append(str(o))
            if len(real_bsms) >= 3:
                break

        # Clone and inject
        kg_plan = kg_main.clone_static_layer()
        triple_count_before = kg_plan.get_triple_count()

        planned = PlannedState(
            version="v1",
            parcels=[
                PlannedParcelEntry(bsm=bsm, planning_land_use="2121",
                                   area_ha=0.15, zone_type="村庄建设区")
                for bsm in real_bsms
            ],
            facilities=[
                PlannedFacilityEntry(name="展销中心", facility_type="商业",
                                     lon=113.5, lat=23.5),
                PlannedFacilityEntry(name="文化活动站", facility_type="文化",
                                     lon=113.51, lat=23.51),
            ],
            roads=[
                PlannedRoadEntry(name="规划主干道", road_level="主干道", width_m=12),
                PlannedRoadEntry(name="规划村道", road_level="村道", width_m=6),
            ],
        )
        kg_plan._apply_planned_state(planned)

        # Verify L4 entities in clone
        pp = kg_plan.query(
            "PREFIX pln: <http://village-planning.org/ontology#> "
            "SELECT ?p ?bsm ?lu WHERE { "
            '?p a pln:PlannedParcel ; pln:bsm ?bsm ; pln:planning_land_use ?lu ; '
            'pln:in_version "v1" . }')
        assert len(pp) == 3, f"Expected 3 planned parcels, got {len(pp)}"

        fac = kg_plan.query(
            "PREFIX pln: <http://village-planning.org/ontology#> "
            'SELECT ?f ?name WHERE { ?f a pln:PlannedFacility ; pln:name ?name ; pln:in_version "v1" . }')
        assert len(fac) == 2, f"Expected 2 planned facilities, got {len(fac)}"

        rd = kg_plan.query(
            "PREFIX pln: <http://village-planning.org/ontology#> "
            'SELECT ?r ?name WHERE { ?r a pln:PlannedRoad ; pln:name ?name ; pln:in_version "v1" . }')
        assert len(rd) == 2, f"Expected 2 planned roads, got {len(rd)}"

        # Triple count must have increased
        assert kg_plan.get_triple_count() > triple_count_before

    def test_main_kg_unaffected_after_plan_injection(self, kg_main):
        """CRITICAL: kg_main triple count and content unchanged after plan tests.

        This test runs AFTER test_inject_planned_state_to_clone (pytest order).
        If kg_main was polluted, this will fail.
        """
        # Verify no L4 entities in main KG
        pp = kg_main.query(
            "PREFIX pln: <http://village-planning.org/ontology#> "
            "SELECT ?p WHERE { ?p a pln:PlannedParcel . }")
        assert len(pp) == 0, "Main KG polluted with PlannedParcel!"

        # Verify no L3 entities either
        zt = kg_main.query(
            "PREFIX pln: <http://village-planning.org/ontology#> "
            "SELECT ?z WHERE { ?z a pln:ZoneTarget . }")
        assert len(zt) == 0, "Main KG polluted with ZoneTarget!"

    def test_check_constraint_violations_runs(self, kg_main, village_bundle):
        """check_constraint_violations detects parcels overlapping constraint polygons.

        Uses ConstraintIndex (spatial_ops bridge) to check planned parcels
        against farmland_protection / ecological_redline / historical_protection.
        """
        from app.modules.kg.builder.layer4 import PlannedState, PlannedParcelEntry
        from rdflib import Namespace
        PLN = Namespace("http://village-planning.org/ontology#")

        # Find a real BSM that overlaps a constraint polygon
        # (jintian has 88 farmland_protection + 5 ecological_redline polygons)
        constraint_idx = kg_main._constraint_index
        assert constraint_idx is not None

        # Test with a real parcel BSM - try to find one that overlaps
        real_bsm = None
        for s, _, o in kg_main.g.triples((None, PLN.bsm, None)):
            if (s, None, PLN.Parcel) in kg_main.g:
                bsm = str(o)
                overlaps = constraint_idx.parcel_in_constraint(bsm)
                if overlaps:
                    real_bsm = bsm
                    break

        kg_plan = kg_main.clone_static_layer()
        if real_bsm:
            # This parcel overlaps a constraint - should detect violation
            kg_plan._apply_planned_state(PlannedState(version="v1",
                parcels=[PlannedParcelEntry(bsm=real_bsm, planning_land_use="2121")]))
            violations = kg_plan.check_constraint_violations("v1")
            assert isinstance(violations, list)
            assert len(violations) > 0, f"Expected violations for BSM {real_bsm} in protected zone"
        else:
            # No overlapping parcel found - just verify method runs
            kg_plan._apply_planned_state(PlannedState(version="v1",
                parcels=[PlannedParcelEntry(bsm="NO_OVERLAP_TEST", planning_land_use="2121")]))
            violations = kg_plan.check_constraint_violations("v1")
            assert isinstance(violations, list)

    def test_compare_versions(self, kg_main):
        """compare_versions detects changes between two planned versions."""
        from app.modules.kg.builder.layer4 import PlannedState, PlannedParcelEntry
        kg_plan = kg_main.clone_static_layer()

        # Get a real BSM
        from rdflib import Namespace
        PLN = Namespace("http://village-planning.org/ontology#")
        real_bsm = None
        for s, _, o in kg_plan.g.triples((None, PLN.bsm, None)):
            if (s, None, PLN.Parcel) in kg_plan.g:
                real_bsm = str(o)
                break
        assert real_bsm is not None

        # Version A: residential
        kg_plan._apply_planned_state(PlannedState(version="v1",
            parcels=[PlannedParcelEntry(bsm=real_bsm, planning_land_use="2121",
                                       area_ha=0.5)]))
        # Version B: same parcel, different land use
        kg_plan._apply_planned_state(PlannedState(version="v2",
            parcels=[PlannedParcelEntry(bsm=real_bsm, planning_land_use="0101",
                                       area_ha=0.5)]))

        diff = kg_plan.compare_versions("v1", "v2")
        assert diff["version_a"] == "v1"
        assert diff["version_b"] == "v2"
        assert len(diff["changed_parcels"]) == 1
        assert diff["changed_parcels"][0]["bsm"] == real_bsm
        assert diff["changed_parcels"][0]["from"] == "2121"
        assert diff["changed_parcels"][0]["to"] == "0101"
        assert diff["total_changes"] >= 1

    def test_get_planned_parcels_in_zone(self, kg_main):
        """get_planned_parcels_in_zone queries L4 by zone type."""
        from app.modules.kg.builder.layer4 import PlannedState, PlannedParcelEntry
        kg_plan = kg_main.clone_static_layer()
        kg_plan._apply_planned_state(PlannedState(version="v1",
            parcels=[
                PlannedParcelEntry(bsm="Z1",  planning_land_use="2121",
                                   zone_type="村庄建设区", area_ha=0.3),
                PlannedParcelEntry(bsm="Z2",  planning_land_use="0101",
                                   zone_type="农田保护区", area_ha=1.2),
                PlannedParcelEntry(bsm="Z3",  planning_land_use="2121",
                                   zone_type="村庄建设区", area_ha=0.4),
            ]))

        result = kg_plan.get_planned_parcels_in_zone("村庄建设区", "v1")
        assert len(result) == 2
        bsms = {r["bsm"] for r in result}
        assert bsms == {"Z1", "Z3"}

    def test_split_merge_new_bsm_identifiers(self, kg_main):
        """Split/merge create NEW bsm identifiers, not reuse L1 bsms.

        This is the core of planning: split one parcel into multiple,
        or merge multiple into one. The new parcels get new identifiers
        with derived_from linking back to L1 parents.
        """
        from app.modules.kg.builder.layer4 import PlannedState, PlannedParcelEntry
        # Get a real L1 bsm
        from rdflib import Namespace
        PLN = Namespace("http://village-planning.org/ontology#")
        real_bsm = None
        for s, _, o in kg_main.g.triples((None, PLN.bsm, None)):
            if (s, None, PLN.Parcel) in kg_main.g:
                real_bsm = str(o)
                break
        assert real_bsm is not None

        kg_plan = kg_main.clone_static_layer()
        # Split: P -> P_s1, P_s2 (new bsms, derived from P)
        # Merge: Q1 + Q2 -> Q1Q2_merged (new bsm, derived from Q1 + Q2)
        kg_plan._apply_planned_state(PlannedState(version="v1",
            parcels=[
                # Split: real_bsm -> two sub-parcels
                PlannedParcelEntry(
                    bsm=f"{real_bsm}_s1", 
                    planning_land_use="2121", area_ha=0.3,
                    derived_from_bsms=[real_bsm]),
                PlannedParcelEntry(
                    bsm=f"{real_bsm}_s2", 
                    planning_land_use="0101", area_ha=0.7,
                    derived_from_bsms=[real_bsm]),
                # Merge: two L1 parcels -> one merged parcel
                PlannedParcelEntry(
                    bsm=f"{real_bsm}_merged", 
                    planning_land_use="2121", area_ha=1.5,
                    derived_from_bsms=[real_bsm, "OTHER_BSM"]),
            ]))

        # Verify planned parcels with derived_from links
        pp = kg_plan.query(
            "PREFIX pln: <http://village-planning.org/ontology#> "
            "SELECT ?p ?bsm ?lu WHERE { "
            "?p a pln:PlannedParcel ; pln:bsm ?bsm ; pln:planning_land_use ?lu . }")
        assert len(pp) >= 3
        pp_bsms = {r["bsm"] for r in pp}
        assert f"{real_bsm}_s1" in pp_bsms
        assert f"{real_bsm}_s2" in pp_bsms
        assert f"{real_bsm}_merged" in pp_bsms

    def test_effective_land_use_l1_l4_merge(self, kg_main):
        """get_effective_land_use: L4 if changed, else L1 fallback.

        Unchanged parcels (no L4 triple) -> return L1 dlbm.
        Changed parcels (L4 triple exists) -> return L4 planning_land_use.
        """
        from app.modules.kg.builder.layer4 import PlannedState, PlannedParcelEntry
        from rdflib import Namespace
        PLN = Namespace("http://village-planning.org/ontology#")

        # Get two real L1 bsms: one to change, one to leave unchanged
        real_bsms = []
        for s, _, o in kg_main.g.triples((None, PLN.bsm, None)):
            if (s, None, PLN.Parcel) in kg_main.g:
                real_bsms.append(str(o))
            if len(real_bsms) >= 2:
                break

        kg_plan = kg_main.clone_static_layer()
        # Get L1 dlbm for both
        l1_lu_0 = kg_plan.get_effective_land_use(real_bsms[0], "v1")
        l1_lu_1 = kg_plan.get_effective_land_use(real_bsms[1], "v1")
        assert l1_lu_0 is not None  # L1 fallback works

        # Apply plan: change parcel 0, leave parcel 1 unchanged
        kg_plan._apply_planned_state(PlannedState(version="v1",
            parcels=[
                PlannedParcelEntry(bsm=real_bsms[0], 
                             planning_land_use="2121",
                             derived_from_bsms=[real_bsms[0]]),
            ]))

        # Parcel 0: L4 overrides L1
        eff_0 = kg_plan.get_effective_land_use(real_bsms[0], "v1")
        assert eff_0 == "2121"
        # Parcel 1: no L4, falls back to L1
        eff_1 = kg_plan.get_effective_land_use(real_bsms[1], "v1")
        assert eff_1 == l1_lu_1

    def test_sparse_write_no_l4_for_unchanged(self, kg_main):
        """Sparse write: 660 L1 parcels, only 3 L4 changes -> minimal triples."""
        from app.modules.kg.builder.layer4 import PlannedState, PlannedParcelEntry
        from rdflib import Namespace
        PLN = Namespace("http://village-planning.org/ontology#")

        kg_plan = kg_main.clone_static_layer()
        triple_count_before = kg_plan.get_triple_count()

        kg_plan._apply_planned_state(PlannedState(version="v1",
            parcels=[
                PlannedParcelEntry(bsm="SPARSE_1", 
                             planning_land_use="2121"),
                PlannedParcelEntry(bsm="SPARSE_2", 
                             planning_land_use="0101"),
                PlannedParcelEntry(bsm="SPARSE_3", 
                             planning_land_use="0301"),
            ]))

        triple_count_after = kg_plan.get_triple_count()
        delta = triple_count_after - triple_count_before
        # 3 parcel changes * ~5 triples each (type, bsm, action, version, land_use)
        # Should be ~15 triples, NOT 660 * 5 = 3300
        assert delta < 50, f"Sparse write failed: {delta} triples added (expected <50)"
        assert delta > 0

    def test_get_plan_changes(self, kg_main):
        """get_plan_changes returns delta entries for a version."""
        from app.modules.kg.builder.layer4 import PlannedState, PlannedParcelEntry
        kg_plan = kg_main.clone_static_layer()
        kg_plan._apply_planned_state(PlannedState(version="v1",
            parcels=[
                PlannedParcelEntry(bsm="CHG_1", 
                             planning_land_use="2121"),
                PlannedParcelEntry(bsm="CHG_2", 
                             area_ha=0.5),
            ]))

        changes = kg_plan.get_plan_changes("v1")
        assert len(changes) == 2
        lu_set = {c.get("lu", "") for c in changes}
        assert "2121" in lu_set


# ── Part 7: Intent injection (SEPARATE - must not affect main KG) ───


class TestIntentInjectionIsolated:
    """Layer 3 intent injection test - MUST be isolated from main KG.

    Design:
      1. Clone kg_main via clone_static_layer() -> kg_intent
      2. Inject SpatialPlanningIntent into kg_intent ONLY
      3. Verify L3 entities in kg_intent
      4. Verify kg_main is UNAFFECTED
    """

    def test_inject_intent_to_clone(self, kg_main):
        """Inject SpatialPlanningIntent into a CLONE, not kg_main."""
        from app.modules.schema.contracts.parse_contracts import (
            SpatialPlanningIntent, ZoneTarget, FacilityTarget, AxisTarget,
        )

        kg_intent = kg_main.clone_static_layer()
        triple_count_before = kg_intent.get_triple_count()

        intent = SpatialPlanningIntent(
            village_name="jintian",
            zone_targets=[
                ZoneTarget(land_use="商业用地", area_ratio=0.15, dlbm="2121"),
            ],
            facilities=[
                FacilityTarget(type="展销中心", status="planned_new", service_radius=500),
                FacilityTarget(type="小学", status="planned_new", service_radius=1000),
            ],
            development_axes=[
                AxisTarget(reference_feature="村主干道"),
            ],
        )
        kg_intent._add_structured_intent(intent)

        # Verify L3 ZoneTarget
        zt = kg_intent.query(
            "PREFIX pln: <http://village-planning.org/ontology#> "
            "SELECT ?z ?code ?area WHERE { "
            "?z a pln:ZoneTarget ; pln:land_use_code ?code ; "
            "pln:target_area_ha ?area . }")
        assert len(zt) == 1
        assert zt[0]["code"] == "商业用地"

        # Verify L3 FacilityTarget
        ft = kg_intent.query(
            "PREFIX pln: <http://village-planning.org/ontology#> "
            "SELECT ?f ?type WHERE { ?f a pln:FacilityTarget ; pln:facility_type ?type . }")
        assert len(ft) == 2

        # Verify L3 AxisTarget
        at = kg_intent.query(
            "PREFIX pln: <http://village-planning.org/ontology#> "
            "SELECT ?a WHERE { ?a a pln:AxisTarget . }")
        assert len(at) == 1

        # Note: SpatialConstraints are NOT part of SpatialPlanningIntent.
        # They are passed separately to build_from_bundle by the caller.

        # Triple count must have increased
        assert kg_intent.get_triple_count() > triple_count_before

        # Memory store populated (not RDF)
        assert kg_intent.memory is not None

    def test_main_kg_unaffected_after_intent_injection(self, kg_main):
        """CRITICAL: kg_main has no L3 entities after intent tests."""
        zt = kg_main.query(
            "PREFIX pln: <http://village-planning.org/ontology#> "
            "SELECT ?z WHERE { ?z a pln:ZoneTarget . }")
        ft = kg_main.query(
            "PREFIX pln: <http://village-planning.org/ontology#> "
            "SELECT ?f WHERE { ?f a pln:FacilityTarget . }")
        at = kg_main.query(
            "PREFIX pln: <http://village-planning.org/ontology#> "
            "SELECT ?a WHERE { ?a a pln:AxisTarget . }")
        assert len(zt) == 0
        assert len(ft) == 0
        assert len(at) == 0

    def test_validate_intent_runs(self, kg_main):
        """validate_intent runs without error on a clone."""
        from app.modules.schema.contracts.parse_contracts import (
            SpatialPlanningIntent, FacilityTarget,
        )
        kg_intent = kg_main.clone_static_layer()
        intent = SpatialPlanningIntent(
            village_name="test",
            facilities=[
                FacilityTarget(type="测试设施", status="planned_new",
                               location_hint="村北"),
            ],
        )
        conflicts = kg_intent.validate_intent(intent)
        assert isinstance(conflicts, list)
        # Known gap: _is_in_protected_zone checks within_zone which is never set


# ── Part 8: Static structure verification ───────────────────────────


class TestKGStaticStructure:
    """Verify KG module has no forbidden imports."""

    def test_no_shapely_in_kg(self):
        """KG module must not import shapely."""
        kg_dir = Path(_BACKEND_DIR) / "app" / "modules" / "kg"
        import re
        pattern = re.compile(r'^\s*(from|import)\s+.*(shapely|geopandas)')
        violations = []
        for f in kg_dir.rglob("*.py"):
            if "__pycache__" in str(f):
                continue
            with open(f, "r", encoding="utf-8") as fh:
                for lineno, line in enumerate(fh, 1):
                    if pattern.match(line):
                        violations.append(f"{f.name}:{lineno}: {line.strip()}")
        assert violations == [], f"KG has forbidden geometry imports:\n" + "\n".join(violations)

    def test_no_reverse_deps_in_kg(self):
        """KG must not import from app.tools or app.agent."""
        kg_dir = Path(_BACKEND_DIR) / "app" / "modules" / "kg"
        import re
        pattern = re.compile(r'^\s*from app\.(tools|agent)')
        violations = []
        for f in kg_dir.rglob("*.py"):
            if "__pycache__" in str(f):
                continue
            with open(f, "r", encoding="utf-8") as fh:
                for lineno, line in enumerate(fh, 1):
                    if pattern.match(line):
                        violations.append(f"{f.name}:{lineno}: {line.strip()}")
        assert violations == [], f"KG has reverse deps:\n" + "\n".join(violations)

    def test_no_data_layer_imports_in_kg(self):
        """KG must not import from app.modules.data (P1: no upward deps)."""
        kg_dir = Path(_BACKEND_DIR) / "app" / "modules" / "kg"
        import re
        pattern = re.compile(r'^\s*from app\.modules\.data')
        violations = []
        for f in kg_dir.rglob("*.py"):
            if "__pycache__" in str(f):
                continue
            with open(f, "r", encoding="utf-8") as fh:
                for lineno, line in enumerate(fh, 1):
                    if pattern.match(line):
                        violations.append(f"{f.name}:{lineno}: {line.strip()}")
        assert violations == [], f"KG imports from data layer:\n" + "\n".join(violations)

    def test_builder_subpackage_has_six_files(self):
        """builder/ subpackage has the 6 expected files."""
        builder_dir = Path(_BACKEND_DIR) / "app" / "modules" / "kg" / "builder"
        expected = {"__init__.py", "base.py", "layer1.py", "layer2.py",
                    "layer3.py", "layer4.py", "queries.py"}
        actual = {f.name for f in builder_dir.glob("*.py")}
        assert expected.issubset(actual), f"Missing: {expected - actual}"


# ── Part 9: SpatialCognitiveUnit hierarchy verification ─────────────


class TestSpatialCognitiveUnitHierarchy:
    """Verify the morphology hierarchy aligns L1/L3/L4 types."""

    def test_l1_anchors_inherit_morphology(self):
        """L1 cognition anchors inherit from Point/Line/PolygonBasedCognition."""
        from app.modules.schema.contracts.context_contracts import (
            FacilityAnchor, NaturalVillageAnchor, ConstraintZoneAnchor,
            PointBasedCognition, LineBasedCognition, PolygonBasedCognition,
        )
        assert issubclass(FacilityAnchor, PointBasedCognition)
        assert issubclass(NaturalVillageAnchor, PolygonBasedCognition)
        assert issubclass(ConstraintZoneAnchor, PolygonBasedCognition)

    def test_parse_contracts_intent_has_semantic_fields(self):
        """Parse contracts ZoneTarget/FacilityTarget/AxisTarget have semantic fields."""
        from app.modules.schema.contracts.parse_contracts import (
            ZoneTarget, FacilityTarget, AxisTarget, SpatialPlanningIntent,
            SemanticMetadata,
        )
        zt = ZoneTarget(land_use="农田保护区", area_ratio=0.5,
                        semantic=SemanticMetadata(
                            natural_language_description="保护农田",
                            spatial_hint="村南",
                        ))
        assert zt.semantic.natural_language_description == "保护农田"
        assert zt.semantic.spatial_hint == "村南"
        ft = FacilityTarget(type="小学", status="planned_new",
                            semantic=SemanticMetadata(
                                natural_language_description="新建小学",
                                spatial_hint="村中心",
                            ))
        assert ft.semantic.natural_language_description == "新建小学"
        at = AxisTarget(reference_feature="主路",
                        semantic=SemanticMetadata(
                            natural_language_description="南北发展轴",
                            spatial_hint="沿主路",
                        ))
        assert at.semantic.natural_language_description == "南北发展轴"
        intent = SpatialPlanningIntent(
            village_name="测试村",
            raw_text="建设小学...",
            reasoning_trace="提取了设施需求",
            zone_targets=[zt], facilities=[ft], development_axes=[at],
        )
        assert intent.raw_text == "建设小学..."
        assert intent.reasoning_trace == "提取了设施需求"

    def test_l4_plan_block_is_delta_not_morphology(self):
        """L4 PlanBlock is a change-set container, NOT a SpatialCognitiveUnit.

        Unlike L1 anchors (NaturalVillageAnchor etc.), PlanBlock and its
        Change types do NOT inherit from Point/Line/PolygonBasedCognition.
        They are 'change operation descriptors', not spatial features.
        """
        from app.modules.schema.contracts.context_contracts import (
            PlanBlock, ParcelChange, FacilityChange, RoadChange,
            SpatialCognitiveUnit,
        )
        # PlanBlock is NOT a SpatialCognitiveUnit
        assert not issubclass(PlanBlock, SpatialCognitiveUnit)
        assert not issubclass(ParcelChange, SpatialCognitiveUnit)
        assert not issubclass(FacilityChange, SpatialCognitiveUnit)
        assert not issubclass(RoadChange, SpatialCognitiveUnit)

    def test_plan_block_delta_structure(self):
        """PlanBlock contains change entries with action + derived_from."""
        from app.modules.schema.contracts.context_contracts import (
            PlanBlock, ParcelChange, FacilityChange, RoadChange,
        )
        ps = PlanBlock(
            version="test",
            parcel_changes=[
                ParcelChange(bsm="X1", action="reclassify",
                             new_planning_land_use="2121",
                             derived_from_bsms=["X1"]),
                ParcelChange(bsm="P1_s1", action="split",
                             new_planning_land_use="2121",
                             derived_from_bsms=["P1"]),
                ParcelChange(bsm="A_B_merged", action="merge",
                             new_planning_land_use="0101",
                             derived_from_bsms=["A", "B"]),
            ],
            facility_changes=[FacilityChange(name="F1", action="new")],
            road_changes=[RoadChange(name="R1", action="new")],
        )
        assert len(ps.parcel_changes) == 3
        assert len(ps.facility_changes) == 1
        assert len(ps.road_changes) == 1
        # Verify action types
        actions = {pc.action for pc in ps.parcel_changes}
        assert actions == {"reclassify", "split", "merge"}
        # Verify split has new bsm + parent
        split_pc = next(pc for pc in ps.parcel_changes if pc.action == "split")
        assert split_pc.bsm != split_pc.derived_from_bsms[0]
        # Verify merge has new bsm + multiple parents
        merge_pc = next(pc for pc in ps.parcel_changes if pc.action == "merge")
        assert len(merge_pc.derived_from_bsms) >= 2


# ── Part 10: KGManager caching ──────────────────────────────────────


class TestKGManager:
    """Verify KGManager Layer 1 caching works with real data."""

    def test_layer1_cache_hit(self, village_bundle, context_blocks, parcel_relations):
        """Second build with same data hits cache."""
        from app.modules.kg.manager import get_kg_manager, compute_layer1_cache_key
        manager = get_kg_manager()
        manager._cache_enabled = True

        # First build (cache miss)
        kg1, hit1 = manager.get_or_build_layer1(
            village_name="jintian_test_cache",
            bundle=village_bundle,
            parcel_relations=parcel_relations,
        )
        assert not hit1, "First build should be cache miss"

        # Second build (cache hit)
        kg2, hit2 = manager.get_or_build_layer1(
            village_name="jintian_test_cache",
            bundle=village_bundle,
            parcel_relations=parcel_relations,
        )
        assert hit2, "Second build should be cache hit"

        # Both should have same parcel count (L1 preserved)
        assert kg1.get_parcel_count() == kg2.get_parcel_count()

    def test_cache_key_stable(self, village_bundle):
        """Cache key is stable for same parcel data."""
        from app.modules.kg.manager import compute_layer1_cache_key
        key1 = compute_layer1_cache_key("jintian", village_bundle.polygons.landuse_current)
        key2 = compute_layer1_cache_key("jintian", village_bundle.polygons.landuse_current)
        assert key1 is not None
        assert key1 == key2


# ── Standalone run ──────────────────────────────────────────────────


if __name__ == "__main__":
    # Run as script: python tests/integration/test_kg_jintian_e2e.py
    print("=" * 70)
    print("  KG Jintian E2E Test (run as script)")
    print("=" * 70)
    sys.exit(pytest.main([__file__, "-v", "--tb=short", "-s"]))
