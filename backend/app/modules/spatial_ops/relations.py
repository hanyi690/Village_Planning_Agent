"""Spatial relation computation helpers.

Functions that compute topological and directional relations between
spatial entities: village-to-village directions, zone adjacency.

[v4.3] Type-safe: accepts typed feature lists, uses direct attribute access.
"""

from __future__ import annotations

from typing import Any, Dict, List

from app.modules.schema.contracts.context_contracts import (
    ResidentialClusterAnchor,
    SpatialRelation,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)


def _compute_spatial_relations(
    residential_clusters: List[ResidentialClusterAnchor],
) -> List[SpatialRelation]:
    """Compute spatial relations between residential clusters and zones.

    Uses centroid-based direction computation and distance-based topology.
    """
    relations: List[SpatialRelation] = []

    try:
        if len(residential_clusters) < 2:
            return relations

        # Compute pairwise direction relations between clusters
        for i, v1 in enumerate(residential_clusters):
            for j, v2 in enumerate(residential_clusters):
                if i >= j:
                    continue

                dx = v2.center[0] - v1.center[0]  # longitude diff
                dy = v2.center[1] - v1.center[1]  # latitude diff

                # Determine direction
                if abs(dx) < 1e-6 and abs(dy) < 1e-6:
                    continue

                # Use angle to determine primary direction
                import math
                angle = math.degrees(math.atan2(dy, dx))

                if -22.5 <= angle < 22.5:
                    direction = "east_of"
                elif 22.5 <= angle < 67.5:
                    direction = "north_of"  # NE -> primarily north
                elif 67.5 <= angle < 112.5:
                    direction = "north_of"
                elif 112.5 <= angle < 157.5:
                    direction = "north_of"  # NW -> primarily north
                elif angle >= 157.5 or angle < -157.5:
                    direction = "west_of"
                elif -157.5 <= angle < -112.5:
                    direction = "south_of"  # SW -> primarily south
                elif -112.5 <= angle < -67.5:
                    direction = "south_of"
                elif -67.5 <= angle < -22.5:
                    direction = "south_of"  # SE -> primarily south
                else:
                    direction = "near"

                relations.append(SpatialRelation(
                    subject=v2.name,
                    relation=direction,
                    object=v1.name,
                    confidence=0.9,
                    source="geometry_computed",
                ))

                # Add reverse relation
                reverse_map = {
                    "east_of": "west_of",
                    "west_of": "east_of",
                    "north_of": "south_of",
                    "south_of": "north_of",
                    "near": "near",
                }
                relations.append(SpatialRelation(
                    subject=v1.name,
                    relation=reverse_map.get(direction, "near"),
                    object=v2.name,
                    confidence=0.9,
                    source="geometry_computed",
                ))

        # Add containment relations: clusters contained by construction boundary
        for v in residential_clusters:
            relations.append(SpatialRelation(
                subject="construction_boundary",
                relation="contains",
                object=v.name,
                confidence=1.0,
                source="geometry_computed",
            ))

    except Exception as e:
        logger.warning("[relations] Spatial relations failed: %s", e)

    return relations


def _compute_zone_adjacency(parcels: List[Any]) -> Dict[str, List[str]]:
    """Compute zone adjacency matrix from typed land-use parcels.

    Accepts List[BaseLandUseParcel] — uses p.dlbm and shape(p.geometry) directly.
    """
    try:
        from app.modules.schema import get_zone_type_for_dlbm
        from shapely.geometry import shape

        if not parcels:
            return {}

        # Build GeoDataFrame from typed parcels for spatial indexing
        import geopandas as gpd
        from shapely.geometry import shape as shp

        geoms = []
        zone_types = []
        for p in parcels:
            geom = p.geometry
            if geom is None:
                continue
            try:
                geoms.append(shp(geom))
                dlbm = str(p.dlbm).strip()
                zone_types.append(get_zone_type_for_dlbm(dlbm))
            except Exception:
                continue

        if not geoms:
            return {}

        gdf = gpd.GeoDataFrame({"zone_type": zone_types, "geometry": geoms}, crs="EPSG:4326")

        # Build adjacency from touching parcels
        adjacency: Dict[str, set] = {}
        for i in range(len(gdf)):
            zone_i = gdf.iloc[i]["zone_type"]
            if not zone_i:
                continue
            if zone_i not in adjacency:
                adjacency[zone_i] = set()

            geom_i = gdf.iloc[i].geometry
            # Check neighbors (limit to nearby parcels for performance)
            for j in range(max(0, i - 50), min(len(gdf), i + 50)):
                if i == j:
                    continue
                zone_j = gdf.iloc[j]["zone_type"]
                if not zone_j or zone_j == zone_i:
                    continue
                geom_j = gdf.iloc[j].geometry
                if geom_i.touches(geom_j) or geom_i.distance(geom_j) < 0.0001:
                    adjacency[zone_i].add(zone_j)

        return {k: sorted(v) for k, v in adjacency.items() if v}
    except Exception as e:
        logger.warning("[relations] Zone adjacency failed: %s", e)
        return {}
