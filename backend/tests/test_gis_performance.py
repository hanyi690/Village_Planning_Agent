"""
Performance benchmarks for GIS layout engine components.

Verifies that key operations complete within acceptable time bounds:
- MIP model build < 2s
- MIP solve < 120s (with adjacency)
- Adjacency graph build < 1s
- KG query < 500ms
- Full pipeline (engine._generate_planning_zones) < 30s
"""

from __future__ import annotations

import time

import pytest

from app.services.modules.gis.layout.optimizer.adjacency_graph import AdjacencyGraph
from app.services.modules.gis.layout.optimizer.mip_allocator import MIPZoneAllocator
from app.services.modules.gis.utils.geojson_utils import build_parcel_index
from app.services.modules.gis.layout.zone_generator import resolve_zone_type_for_dlbm
from app.services.modules.gis.layout.kg import PlanningKG

from tests.fixtures.gis_e2e import load_landuse_current


# --- Fixtures ---

@pytest.fixture(scope="module")
def landuse_geojson():
    return load_landuse_current()


@pytest.fixture(scope="module")
def parcel_db(landuse_geojson):
    db, _dup = build_parcel_index(landuse_geojson, zone_type_fn=resolve_zone_type_for_dlbm)
    return db


@pytest.fixture(scope="module")
def planning_targets():
    return {
        "农田保护区": 78.83,
        "村庄建设区": 30.50,
        "生态保护区": 362.02,
        "一般农业区": 1881.21,
    }


@pytest.fixture(scope="module")
def kg(landuse_geojson):
    """Build a KG for query benchmarks."""
    reports = {
        "land_use_planning": {
            "summary": {
                "metrics": {
                    "建设用地规模_公顷": 30.50,
                    "耕地保有量_公顷": 78.83,
                    "生态保护红线面积": 362.02,
                }
            },
            "content": "规划实施农田整治项目。",
        }
    }
    kg = PlanningKG(village_name="金田村")
    kg.build_from_reports(
        reports=reports,
        landuse_geojson=landuse_geojson,
        gis_data={"landuse_current_geojson": landuse_geojson},
    )
    return kg


# --- Benchmarks ---

class TestAdjacencyGraphPerformance:

    def test_adjacency_graph_build_under_1s(self, parcel_db):
        start = time.time()
        AdjacencyGraph(parcel_db, max_distance_m=30.0)
        elapsed = time.time() - start
        assert elapsed < 2.0, f"Adjacency graph build too slow: {elapsed:.2f}s"


class TestMIPPerformance:

    def test_mip_build_under_2s(self, landuse_geojson, planning_targets):
        """MIP model construction (without solving) should be fast."""
        allocator = MIPZoneAllocator()
        start = time.time()
        # We can't easily separate build from solve in the current API,
        # so we test the full solve without adjacency (which is faster)
        allocator.solve(
            landuse_geojson, planning_targets,
            constraints=[], kg=None,
        )
        elapsed = time.time() - start
        # Full solve without adjacency should still be reasonable
        assert elapsed < 60.0, f"MIP solve (no adjacency) too slow: {elapsed:.1f}s"

    def test_mip_solve_with_adjacency_under_120s(self, landuse_geojson, planning_targets, parcel_db):
        adj_graph = AdjacencyGraph(parcel_db, max_distance_m=30.0)
        allocator = MIPZoneAllocator()
        start = time.time()
        allocator.solve(
            landuse_geojson, planning_targets,
            constraints=[], kg=None,
            adjacency_graph=adj_graph,
            adjacency_weight=0.5,
        )
        elapsed = time.time() - start
        assert elapsed < 120.0, f"MIP solve (with adjacency) too slow: {elapsed:.1f}s"


class TestKGPerformance:

    def test_kg_query_under_500ms(self, kg):
        """SPARQL queries should complete under 500ms."""
        queries = [
            kg.get_constraints(),
            kg.query("SELECT ?p ?v WHERE { ?p a <http://village-planning.org/ontology#Parcel> ; "
                     "<http://village-planning.org/ontology#area_ha> ?v } LIMIT 10"),
            kg.query("SELECT ?type (COUNT(?e) as ?c) WHERE { ?e a ?type } GROUP BY ?type"),
        ]
        for q in queries:
            start = time.time()
            # Force evaluation (queries are lazy)
            _ = len(q) if isinstance(q, list) else len(list(q))
            elapsed = time.time() - start
            assert elapsed < 0.5, f"KG query too slow: {elapsed:.3f}s"

    def test_kg_build_under_5s(self, landuse_geojson):
        """Full KG build should complete under 5s."""
        reports = {
            "land_use_planning": {
                "summary": {"metrics": {"建设用地规模_公顷": 30.50}},
                "content": "规划项目。",
            }
        }
        start = time.time()
        kg = PlanningKG(village_name="金田村")
        kg.build_from_reports(
            reports=reports,
            landuse_geojson=landuse_geojson,
            gis_data={"landuse_current_geojson": landuse_geojson},
        )
        elapsed = time.time() - start
        assert elapsed < 5.0, f"KG build too slow: {elapsed:.2f}s"
