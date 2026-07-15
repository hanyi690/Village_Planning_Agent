"""
Adjacency graph for parcel spatial relationships.

Builds a neighbor map from landuse GeoJSON using Shapely spatial joins
with distance-based filtering. Used by MIP allocator for adjacency
constraints and spatial compactness metrics.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set, Tuple

from app.utils.logger import get_logger

logger = get_logger(__name__)

try:
    import geopandas as gpd
    import shapely.geometry
    from shapely import STRtree
    GEOPANDAS_AVAILABLE = True
except ImportError:
    GEOPANDAS_AVAILABLE = False


class AdjacencyGraph:
    """Parcel adjacency graph built from spatial joins.

    For N parcels with ~3000-5000 adjacency edges (village-scale),
    this provides O(1) neighbor lookups and index-based pair iteration
    for MIP constraint encoding.
    """

    def __init__(
        self,
        parcel_db: Dict[str, Dict[str, Any]],
        max_distance_m: float = 30.0,
    ) -> None:
        self.adjacency_dict: Dict[str, Set[str]] = {}
        self.parcel_to_idx: Dict[str, int] = {}
        self.idx_to_parcel: Dict[int, str] = {}

        keys = sorted(parcel_db.keys())
        for idx, key in enumerate(keys):
            self.parcel_to_idx[key] = idx
            self.idx_to_parcel[idx] = key
            self.adjacency_dict[key] = set()

        self._build_from_parcels(parcel_db, max_distance_m)

        edge_count = self.get_edge_count()
        logger.info(
            f"[AdjacencyGraph] Built: {len(keys)} parcels, "
            f"{edge_count} adjacency edges (max_dist={max_distance_m}m)"
        )

    def _build_from_parcels(
        self,
        parcel_db: Dict[str, Dict[str, Any]],
        max_distance_m: float,
    ) -> None:
        """Build adjacency using Shapely STRtree + distance check."""
        if not GEOPANDAS_AVAILABLE:
            self._build_fallback(parcel_db, max_distance_m)
            return

        keys = sorted(parcel_db.keys())
        geometries = []
        for key in keys:
            ft = parcel_db[key].get("feature", {})
            geom_data = ft.get("geometry", {})
            try:
                geom = shapely.geometry.shape(geom_data)
                geometries.append(geom if geom.is_valid else geom.buffer(0))
            except Exception:
                geometries.append(None)

        valid_mask = [g is not None for g in geometries]
        valid_geoms = [g for g in geometries if g is not None]
        valid_indices = [i for i, v in enumerate(valid_mask) if v]

        if not valid_geoms:
            logger.warning("[AdjacencyGraph] No valid geometries, graph is empty")
            return

        # Use STRtree for efficient spatial queries
        tree = STRtree(valid_geoms)

        # Distance threshold in degrees (approximate at Chinese latitudes ~30N)
        # 1 degree ≈ 111km * cos(30) ≈ 96km at latitude 30
        max_distance_deg = max_distance_m / 96_000.0

        for local_i, global_i in enumerate(valid_indices):
            geom_i = valid_geoms[local_i]
            # Query tree for candidates within bounding box
            candidates = tree.query(geom_i.buffer(max_distance_deg))

            for local_j in candidates:
                global_j = valid_indices[local_j]
                if global_j <= global_i:
                    continue

                geom_j = valid_geoms[local_j]
                # Check actual distance (not just bbox overlap)
                try:
                    dist = geom_i.distance(geom_j)
                    dist_m = dist * 96_000.0  # Approximate degree-to-meter
                    if dist_m <= max_distance_m:
                        key_i = keys[global_i]
                        key_j = keys[global_j]
                        self.adjacency_dict[key_i].add(key_j)
                        self.adjacency_dict[key_j].add(key_i)
                except Exception:
                    pass

    def _build_fallback(
        self,
        parcel_db: Dict[str, Dict[str, Any]],
        max_distance_m: float,
    ) -> None:
        """Fallback: build adjacency from centroid distances when geopandas unavailable."""
        import math

        keys = sorted(parcel_db.keys())
        centroids = []
        for key in keys:
            ft = parcel_db[key].get("feature", {})
            geom = ft.get("geometry", {})
            coords = self._extract_centroid(geom)
            centroids.append(coords)

        max_distance_deg = max_distance_m / 96_000.0
        for i in range(len(keys)):
            if centroids[i] is None:
                continue
            for j in range(i + 1, len(keys)):
                if centroids[j] is None:
                    continue
                dx = centroids[i][0] - centroids[j][0]
                dy = centroids[i][1] - centroids[j][1]
                if abs(dx) > max_distance_deg * 2 or abs(dy) > max_distance_deg * 2:
                    continue
                dist = math.sqrt(dx * dx + dy * dy)
                if dist <= max_distance_deg:
                    self.adjacency_dict[keys[i]].add(keys[j])
                    self.adjacency_dict[keys[j]].add(keys[i])

    @staticmethod
    def _extract_centroid(geom: Dict[str, Any]) -> Optional[List[float]]:
        """Extract centroid from a GeoJSON geometry dict."""
        gtype = geom.get("type", "")
        coords = geom.get("coordinates", [])
        if not coords:
            return None
        if gtype == "Point":
            return coords
        if gtype in ("Polygon", "MultiPoint"):
            ring = coords[0] if coords else []
            if ring:
                return [sum(c[0] for c in ring) / len(ring),
                        sum(c[1] for c in ring) / len(ring)]
        if gtype == "MultiPolygon":
            all_pts = []
            for poly in coords:
                if poly and poly[0]:
                    all_pts.extend(poly[0])
            if all_pts:
                return [sum(c[0] for c in all_pts) / len(all_pts),
                        sum(c[1] for c in all_pts) / len(all_pts)]
        return None

    def get_adjacent_pairs(self) -> List[Tuple[str, str]]:
        """Return all adjacency pairs (deduplicated, key_i < key_j)."""
        pairs = []
        for key_i, neighbors in self.adjacency_dict.items():
            for key_j in neighbors:
                if key_i < key_j:
                    pairs.append((key_i, key_j))
        return pairs

    def get_neighbors(self, parcel_key: str) -> Set[str]:
        """Return neighbors of a specific parcel."""
        return self.adjacency_dict.get(parcel_key, set())

    def get_edge_count(self) -> int:
        """Return total number of adjacency edges."""
        return sum(len(ns) for ns in self.adjacency_dict.values()) // 2

    def to_index_pairs(self) -> List[Tuple[int, int]]:
        """Return index-based adjacency pairs for MIP constraint encoding."""
        pairs = []
        for key_i, neighbors in self.adjacency_dict.items():
            idx_i = self.parcel_to_idx[key_i]
            for key_j in neighbors:
                if key_i < key_j:
                    idx_j = self.parcel_to_idx[key_j]
                    pairs.append((idx_i, idx_j))
        return pairs

    def get_parcel_count(self) -> int:
        """Return number of parcels in the graph."""
        return len(self.parcel_to_idx)


__all__ = ["AdjacencyGraph"]
