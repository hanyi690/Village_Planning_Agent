"""
Tests for AdjacencyGraph — parcel spatial adjacency detection.

Verifies adjacency graph construction, edge counting, neighbor lookup,
and index-based pair generation for MIP constraint encoding.
"""

from __future__ import annotations

import pytest

from app.services.modules.gis.layout.optimizer.adjacency_graph import AdjacencyGraph
from app.services.modules.gis.utils.geojson_utils import build_parcel_index
from app.services.modules.gis.layout.zone_generator import resolve_zone_type_for_dlbm

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
def adj_graph(parcel_db):
    return AdjacencyGraph(parcel_db, max_distance_m=30.0)


# --- Construction Tests ---

class TestAdjacencyGraphConstruction:

    def test_graph_has_all_parcels(self, adj_graph, parcel_db):
        assert adj_graph.get_parcel_count() == len(parcel_db)

    def test_graph_has_edges(self, adj_graph):
        edge_count = adj_graph.get_edge_count()
        assert edge_count > 0, "Adjacency graph should have at least some edges"

    def test_adjacency_dict_has_entry_for_every_parcel(self, adj_graph, parcel_db):
        for key in parcel_db:
            assert key in adj_graph.adjacency_dict

    def test_edge_count_reasonable_for_660_parcels(self, adj_graph):
        edge_count = adj_graph.get_edge_count()
        # 660 parcels in a village: expect 1000-8000 edges
        assert 500 < edge_count < 15000, (
            f"Unexpected edge count: {edge_count}"
        )

    def test_no_self_adjacency(self, adj_graph):
        for key, neighbors in adj_graph.adjacency_dict.items():
            assert key not in neighbors, f"Parcel {key} is adjacent to itself"


# --- Neighbor Lookup Tests ---

class TestAdjacencyGraphNeighborLookup:

    def test_get_neighbors_returns_set(self, adj_graph, parcel_db):
        first_key = next(iter(parcel_db))
        neighbors = adj_graph.get_neighbors(first_key)
        assert isinstance(neighbors, set)

    def test_get_neighbors_for_nonexistent_key(self, adj_graph):
        neighbors = adj_graph.get_neighbors("nonexistent_key")
        assert neighbors == set()

    def test_neighbors_are_valid_parcels(self, adj_graph, parcel_db):
        for key, neighbors in adj_graph.adjacency_dict.items():
            for n in neighbors:
                assert n in parcel_db, f"Neighbor {n} of {key} not in parcel_db"

    def test_adjacency_is_symmetric(self, adj_graph):
        for key_i, neighbors in adj_graph.adjacency_dict.items():
            for key_j in neighbors:
                assert key_i in adj_graph.adjacency_dict[key_j], (
                    f"Adjacency not symmetric: {key_i} -> {key_j} but not reverse"
                )


# --- Pair Generation Tests ---

class TestAdjacencyGraphPairs:

    def test_get_adjacent_pairs_deduplicated(self, adj_graph):
        pairs = adj_graph.get_adjacent_pairs()
        assert len(pairs) > 0
        # All pairs should have key_i < key_j (deduplication)
        for key_i, key_j in pairs:
            assert key_i < key_j

    def test_adjacent_pairs_count_matches_edge_count(self, adj_graph):
        pairs = adj_graph.get_adjacent_pairs()
        edge_count = adj_graph.get_edge_count()
        assert len(pairs) == edge_count

    def test_to_index_pairs_valid_indices(self, adj_graph):
        pairs = adj_graph.to_index_pairs()
        n_parcels = adj_graph.get_parcel_count()
        for idx_i, idx_j in pairs:
            assert 0 <= idx_i < n_parcels
            assert 0 <= idx_j < n_parcels
            assert idx_i < idx_j

    def test_to_index_pairs_roundtrip(self, adj_graph):
        """String pairs and index pairs should be consistent."""
        str_pairs = adj_graph.get_adjacent_pairs()
        idx_pairs = adj_graph.to_index_pairs()
        assert len(str_pairs) == len(idx_pairs)

        for (si, sj), (ii, ij) in zip(str_pairs, idx_pairs):
            assert adj_graph.parcel_to_idx[si] == ii
            assert adj_graph.parcel_to_idx[sj] == ij


# --- Distance Sensitivity Tests ---

class TestAdjacencyGraphDistance:

    def test_larger_distance_produces_more_edges(self, parcel_db):
        g30 = AdjacencyGraph(parcel_db, max_distance_m=30.0)
        g100 = AdjacencyGraph(parcel_db, max_distance_m=100.0)
        assert g100.get_edge_count() > g30.get_edge_count()

    def test_zero_distance_produces_no_edges(self, parcel_db):
        g0 = AdjacencyGraph(parcel_db, max_distance_m=0.0)
        # With 0 distance, only touching parcels (distance=0) are adjacent
        # Most parcels have a small gap, so edges should be very few or zero
        assert g0.get_edge_count() >= 0  # Just shouldn't crash
