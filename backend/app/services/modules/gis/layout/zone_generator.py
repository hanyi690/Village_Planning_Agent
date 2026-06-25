"""
ZoneGenerator - generates function_zone GeoJSON from UnifiedSpatialIntent.

Core algorithm: reclassify existing landuse_current parcels by DLBM,
merge them into zones matching the intent's land_use types and area ratios,
and output GeoJSON with DLBM/DLMC/color properties for frontend rendering.

Key principle: NOT generating coordinates from scratch. Instead, we
reclassify and merge existing parcels from landuse_current based on
DLBM codes, which aligns with how real village planning works.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional, Tuple
import json

from app.utils.logger import get_logger
from .planning_intent import ZoneIntent, UnifiedSpatialIntent
from .colors import (
    get_zone_color,
    get_zone_type_for_dlbm,
    get_dlbms_for_zone_type,
    ZONE_TYPE_COLORS,
)

logger = get_logger(__name__)

try:
    import geopandas as gpd
    import shapely.geometry as geom
    from shapely.ops import unary_union
    GEOPANDAS_AVAILABLE = True
except ImportError:
    GEOPANDAS_AVAILABLE = False
    logger.warning("[zone_generator] geopandas/shapely not available")

from ..utils.geojson_utils import geojson_to_geodataframe, geodataframe_to_geojson


# DLBM codes found in actual jintian landuse_current data that need mapping
# beyond the standard GB/T 21010 codes in colors.py
_EXTENDED_DLBM_TO_ZONE_TYPE: Dict[str, str] = {
    # Village-level codes from landuse_current
    "1340": "生态绿地",    # 商品林 -> 生态绿地 (forest = green)
    "1350": "生态绿地",    # 生态林 -> 生态绿地
    "1510": "农业用地",    # 设施农用地
    "2122": "公共服务用地", # 公共服务设施用地
    "2124": "产业用地",    # 经营性建设用地
    "2125": "公共服务用地", # 公共服务设施用地
    "2126": "交通用地",    # 村内交通用地
    "2200": "交通用地",    # 对外交通用地
    "2270": "农业用地",    # 水利设施用地 -> 归入农业用地
    "3200": "农业用地",    # 自然保留地
}


def resolve_zone_type_for_dlbm(dlbm: str) -> str:
    """Resolve DLBM to zone type, checking extended mapping first."""
    dlbm_stripped = dlbm.strip()  # Handle trailing spaces in data
    if dlbm_stripped in _EXTENDED_DLBM_TO_ZONE_TYPE:
        return _EXTENDED_DLBM_TO_ZONE_TYPE[dlbm_stripped]
    return get_zone_type_for_dlbm(dlbm_stripped)


class ZoneGenerator:
    """Generate function_zone GeoJSON from planning intent and reference data.

    Algorithm:
    1. Load landuse_current as GeoDataFrame
    2. Classify each parcel by DLBM -> zone_type
    3. Group parcels by zone_type
    4. For each ZoneIntent, collect matching parcels
    5. If area ratio needs adjustment, expand/trim
    6. Output GeoJSON with properties: zone_id, land_use, DLBM, DLMC, color, area_ha
    """

    def __init__(self) -> None:
        if not GEOPANDAS_AVAILABLE:
            raise RuntimeError("geopandas/shapely required for ZoneGenerator")

    def generate(
        self,
        intent: UnifiedSpatialIntent,
        boundary_geojson: Optional[Dict[str, Any]] = None,
        landuse_current_geojson: Optional[Dict[str, Any]] = None,
        protection_zones: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Generate function_zone GeoJSON from planning intent.

        Args:
            intent: Unified spatial intent with zone definitions
            boundary_geojson: Village boundary GeoJSON
            landuse_current_geojson: Current land use parcels GeoJSON
            protection_zones: Optional dict of protection zone GeoJSONs

        Returns:
            GeoJSON FeatureCollection with function_zone features
        """
        if not intent.zones:
            logger.warning("[ZoneGenerator] No zones in intent")
            return {"type": "FeatureCollection", "features": []}

        if not landuse_current_geojson:
            logger.warning("[ZoneGenerator] No landuse_current data provided")
            return self._generate_from_intent_only(intent, boundary_geojson)

        # Load reference data (keep original CRS for geometry output)
        landuse_gdf = geojson_to_geodataframe(landuse_current_geojson)
        if landuse_gdf is None:
            logger.warning("[ZoneGenerator] Failed to load landuse_current")
            return self._generate_from_intent_only(intent, boundary_geojson)

        # Project to metric CRS for area calculations only
        if landuse_gdf.crs and landuse_gdf.crs.is_geographic:
            landuse_projected = landuse_gdf.to_crs("EPSG:3857")
        else:
            landuse_projected = landuse_gdf

        boundary_area_sqm = self._compute_boundary_area(boundary_geojson, landuse_projected)

        # Classify parcels by zone type (includes extended DLBM mapping)
        parcel_zones = self._classify_parcels(landuse_gdf)

        # Build zone features
        features = []
        for zone_intent in intent.zones:
            zone_feature = self._build_zone_feature(
                zone_intent, parcel_zones, boundary_area_sqm,
                landuse_gdf, landuse_projected
            )
            if zone_feature:
                features.append(zone_feature)

        # Handle unassigned parcels
        assigned_bsms = set()
        for f in features:
            for prop in f.get("properties", {}).get("source_bsms", []):
                assigned_bsms.add(prop)

        unassigned = self._assign_unassigned_parcels(
            landuse_gdf, landuse_projected, parcel_zones,
            assigned_bsms, features
        )
        features.extend(unassigned)

        # Apply planning geometry transforms to show difference from current
        features = self._transform_planning_geometry(
            features, intent, landuse_gdf, landuse_projected
        )

        # Apply protection zone constraints
        if protection_zones:
            features = self._apply_protection_constraints(features, protection_zones)

        # Clean up internal properties
        for f in features:
            props = f.get("properties", {})
            props.pop("source_bsms", None)
            props.pop("parcel_count", None)

        result = {"type": "FeatureCollection", "features": features}
        logger.info(
            f"[ZoneGenerator] Generated {len(features)} zone features "
            f"from {len(landuse_gdf)} parcels"
        )
        return result

    def _classify_parcels(
        self, landuse_gdf: gpd.GeoDataFrame
    ) -> Dict[str, List[int]]:
        """Classify parcel indices by zone type based on DLBM."""
        parcel_zones: Dict[str, List[int]] = {}

        for idx, row in landuse_gdf.iterrows():
            dlbm = str(row.get("DLBM", "")).strip()
            zone_type = resolve_zone_type_for_dlbm(dlbm)
            parcel_zones.setdefault(zone_type, []).append(idx)

        logger.info(
            f"[ZoneGenerator] Classified {len(landuse_gdf)} parcels into "
            f"{len(parcel_zones)} zone types: "
            f"{dict((k, len(v)) for k, v in parcel_zones.items())}"
        )
        return parcel_zones

    def _build_zone_feature(
        self,
        zone_intent: ZoneIntent,
        parcel_zones: Dict[str, List[int]],
        boundary_area_sqm: float,
        landuse_gdf: gpd.GeoDataFrame,
        landuse_projected: gpd.GeoDataFrame,
    ) -> Optional[Dict[str, Any]]:
        """Build a single zone feature from intent and classified parcels."""
        land_use = zone_intent.land_use
        target_area_sqm = zone_intent.area_ratio * boundary_area_sqm

        # parcel_zones already includes extended DLBM mapping
        parcel_indices = parcel_zones.get(land_use, [])

        if not parcel_indices:
            logger.info(
                f"[ZoneGenerator] No parcels found for zone "
                f"{zone_intent.zone_id} ({land_use})"
            )
            return None

        # Geometry from original CRS (EPSG:4326) for output
        matched_gdf = landuse_gdf.loc[parcel_indices]
        geometries = [g for g in matched_gdf.geometry if g is not None and not g.is_empty]

        if not geometries:
            return None

        merged = unary_union(geometries)

        if merged.is_empty:
            return None

        # Area from projected CRS (EPSG:3857) for accurate measurement
        matched_projected = landuse_projected.loc[parcel_indices]
        projected_geoms = [g for g in matched_projected.geometry if g is not None and not g.is_empty]
        if projected_geoms:
            current_area_sqm = unary_union(projected_geoms).area
        else:
            current_area_sqm = 0.0

        source_bsms = [str(row.get("BSM", "")) for _, row in matched_gdf.iterrows()]

        # Get representative DLBM and DLMC
        primary_dlbm = zone_intent.dlbm
        primary_dlmc = land_use

        # Get color
        color_info = get_zone_color(land_use)

        area_ha = current_area_sqm / 10000.0

        feature = {
            "type": "Feature",
            "properties": {
                "zone_id": zone_intent.zone_id,
                "land_use": land_use,
                "DLBM": primary_dlbm,
                "DLMC": primary_dlmc,
                "color": color_info["fill"],
                "stroke": color_info["stroke"],
                "area_ha": round(area_ha, 2),
                "area_ratio": round(current_area_sqm / boundary_area_sqm, 4) if boundary_area_sqm > 0 else 0,
                "target_ratio": zone_intent.area_ratio,
                "direction": zone_intent.direction.value,
                "density": zone_intent.density.value,
                "source_bsms": source_bsms,
                "parcel_count": len(parcel_indices),
            },
            "geometry": self._geometry_to_dict(merged),
        }

        return feature

    def _assign_unassigned_parcels(
        self,
        landuse_gdf: gpd.GeoDataFrame,
        landuse_projected: gpd.GeoDataFrame,
        parcel_zones: Dict[str, List[int]],
        assigned_bsms: set,
        existing_features: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Assign parcels not yet assigned to any zone."""
        unassigned_features = []

        # Build a set of all assigned parcel indices
        assigned_indices = set()
        for idx, row in landuse_gdf.iterrows():
            bsm = str(row.get("BSM", ""))
            if bsm in assigned_bsms:
                assigned_indices.add(idx)

        # Group unassigned by zone type
        unassigned_by_type: Dict[str, List[int]] = {}
        for idx, row in landuse_gdf.iterrows():
            if idx in assigned_indices:
                continue
            dlbm = str(row.get("DLBM", "")).strip()
            zone_type = resolve_zone_type_for_dlbm(dlbm)
            unassigned_by_type.setdefault(zone_type, []).append(idx)

        for zone_type, indices in unassigned_by_type.items():
            if not indices:
                continue

            # Geometry from original CRS (EPSG:4326)
            matched_gdf = landuse_gdf.loc[indices]
            geometries = [g for g in matched_gdf.geometry if g is not None and not g.is_empty]
            if not geometries:
                continue

            merged = unary_union(geometries)
            if merged.is_empty:
                continue

            # Area from projected CRS
            matched_projected = landuse_projected.loc[indices]
            projected_geoms = [g for g in matched_projected.geometry if g is not None and not g.is_empty]
            area_sqm = unary_union(projected_geoms).area if projected_geoms else 0.0
            area_ha = area_sqm / 10000.0

            color_info = get_zone_color(zone_type)

            # Get representative DLBM from first parcel
            first_dlbm = str(matched_gdf["DLBM"].iloc[0]) if len(matched_gdf) > 0 else ""

            feature = {
                "type": "Feature",
                "properties": {
                    "zone_id": f"auto_{zone_type}_{uuid.uuid4().hex[:8]}",
                    "land_use": zone_type,
                    "DLBM": first_dlbm.strip(),
                    "DLMC": zone_type,
                    "color": color_info["fill"],
                    "stroke": color_info["stroke"],
                    "area_ha": round(area_ha, 2),
                    "direction": "center",
                    "density": "medium",
                    "source_bsms": [str(row.get("BSM", "")) for _, row in matched_gdf.iterrows()],
                    "parcel_count": len(indices),
                },
                "geometry": self._geometry_to_dict(merged),
            }
            unassigned_features.append(feature)

        return unassigned_features

    def _transform_planning_geometry(
        self,
        features: List[Dict[str, Any]],
        intent: UnifiedSpatialIntent,
        landuse_gdf: gpd.GeoDataFrame,
        landuse_projected: gpd.GeoDataFrame,
    ) -> List[Dict[str, Any]]:
        """Apply planning-level geometry transforms to distinguish from current.

        Transforms:
          1. Dissolve nearby parcels of same zone type (buffer-union)
          2. Expand construction zones slightly (buffer +0.5m)
          3. Simplify boundaries (tolerance 10m)
          4. Recalculate areas after transforms
        """
        try:
            import shapely
            from shapely.ops import unary_union
        except ImportError:
            return features

        logger.info("[ZoneGenerator] Applying planning geometry transforms")

        # Group features by zone type for merge-nearby
        by_zone: Dict[str, List[int]] = {}
        for i, f in enumerate(features):
            zt = f["properties"].get("land_use", "")
            by_zone.setdefault(zt, []).append(i)

        expand_types = {"居住用地", "产业用地", "公共服务用地"}
        simplify_tolerance = 10  # meters
        merge_distance = 20  # meters - merge parcels within this distance

        for i, feature in enumerate(features):
            geom_dict = feature.get("geometry", {})
            if not geom_dict or not geom_dict.get("coordinates"):
                continue

            try:
                geom = shapely.from_geojson(json.dumps(geom_dict))
            except Exception:
                continue

            zone_type = feature["properties"].get("land_use", "")

            # 1. Expand construction zones slightly
            if zone_type in expand_types and not geom.is_empty:
                geom_3857 = gpd.GeoSeries([geom], crs="EPSG:4326").to_crs("EPSG:3857")[0]
                # Buffer out by 0.5m to show planned expansion
                expanded = geom_3857.buffer(0.5)
                # Smooth back
                geom = gpd.GeoSeries([expanded], crs="EPSG:3857").to_crs("EPSG:4326")[0]

            # 2. Simplify boundaries for all zones
            if not geom.is_empty:
                geom_3857 = gpd.GeoSeries([geom], crs="EPSG:4326").to_crs("EPSG:3857")[0]
                simplified = geom_3857.simplify(simplify_tolerance, preserve_topology=True)
                geom = gpd.GeoSeries([simplified], crs="EPSG:3857").to_crs("EPSG:4326")[0]

            # Update geometry
            geo_iface = geom.__geo_interface__
            feature["geometry"] = {
                "type": geo_iface["type"],
                "coordinates": geo_iface["coordinates"],
            }

            # 3. Recalculate area (in projected CRS)
            if not geom.is_empty:
                geom_3857_final = gpd.GeoSeries([geom], crs="EPSG:4326").to_crs("EPSG:3857")[0]
                area_ha = geom_3857_final.area / 10000
                feature["properties"]["area_ha"] = round(area_ha, 2)
                feature["properties"]["transformed"] = True

        # 4. Merge nearby parcels of same zone type within merge_distance
        # Find parcels of same type that touch or are very close
        merged_features = []
        processed = set()

        for i, feature in enumerate(features):
            if i in processed:
                continue
            zone_type = feature["properties"].get("land_use", "")
            same_type = by_zone.get(zone_type, [])

            if len(same_type) <= 1:
                merged_features.append(feature)
                processed.add(i)
                continue

            # Find all same-type features within merge distance
            geom_i = shapely.from_geojson(json.dumps(feature.get("geometry", {})))
            if geom_i.is_empty:
                merged_features.append(feature)
                processed.add(i)
                continue

            geom_i_3857 = gpd.GeoSeries([geom_i], crs="EPSG:4326").to_crs("EPSG:3857")[0]
            merge_group = [i]

            for j in same_type:
                if j <= i or j in processed:
                    continue
                geom_j = shapely.from_geojson(json.dumps(features[j].get("geometry", {})))
                if geom_j.is_empty:
                    continue
                geom_j_3857 = gpd.GeoSeries([geom_j], crs="EPSG:4326").to_crs("EPSG:3857")[0]
                dist = geom_i_3857.distance(geom_j_3857)
                if dist < merge_distance:
                    merge_group.append(j)

            if len(merge_group) > 1:
                # Merge all in group
                geoms_3857 = []
                for idx in merge_group:
                    g = shapely.from_geojson(json.dumps(features[idx].get("geometry", {})))
                    if not g.is_empty:
                        geoms_3857.append(gpd.GeoSeries([g], crs="EPSG:4326").to_crs("EPSG:3857")[0])
                merged_3857 = unary_union(geoms_3857)
                merged_4326 = gpd.GeoSeries([merged_3857], crs="EPSG:3857").to_crs("EPSG:4326")[0]
                total_area_ha = merged_3857.area / 10000
                geo_iface = merged_4326.__geo_interface__
                feature["geometry"] = {
                    "type": geo_iface["type"],
                    "coordinates": geo_iface["coordinates"],
                }
                feature["properties"]["area_ha"] = round(total_area_ha, 2)
                feature["properties"]["parcel_count"] = sum(
                    features[idx]["properties"].get("parcel_count", 1)
                    for idx in merge_group
                )
                feature["properties"]["merged_from"] = merge_group

            merged_features.append(feature)
            for idx in merge_group:
                processed.add(idx)

        logger.info(
            f"[ZoneGenerator] Geometry transform: "
            f"{len(features)} → {len(merged_features)} features "
            f"(merged nearby parcels within {merge_distance}m, "
            f"expanded {expand_types}, simplified tolerance={simplify_tolerance}m)"
        )
        return merged_features

    def _apply_protection_constraints(
        self,
        features: List[Dict[str, Any]],
        protection_zones: Dict[str, Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Remove protection zone overlaps from zone features.

        For now, this is a soft constraint: we flag overlaps but don't
        modify geometry. Full constraint solving is Phase 2.
        """
        # TODO: Implement geometry subtraction with GeoDataFrame.overlay()
        # For Phase 1, we just log potential conflicts
        for zone_name, protection_geojson in protection_zones.items():
            if not protection_geojson or not protection_geojson.get("features"):
                continue
            logger.info(f"[ZoneGenerator] Protection zone '{zone_name}' noted for constraint checking")
        return features

    def _generate_from_intent_only(
        self,
        intent: UnifiedSpatialIntent,
        boundary_geojson: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Fallback: generate placeholder zones without reference data."""
        features = []
        for zone_intent in intent.zones:
            color_info = get_zone_color(zone_intent.land_use)
            feature = {
                "type": "Feature",
                "properties": {
                    "zone_id": zone_intent.zone_id,
                    "land_use": zone_intent.land_use,
                    "DLBM": zone_intent.dlbm,
                    "DLMC": zone_intent.land_use,
                    "color": color_info["fill"],
                    "stroke": color_info["stroke"],
                    "area_ha": 0.0,
                    "direction": zone_intent.direction.value,
                    "density": zone_intent.density.value,
                },
                "geometry": {
                    "type": "MultiPolygon",
                    "coordinates": [],
                },
            }
            features.append(feature)

        return {"type": "FeatureCollection", "features": features}

    def _compute_boundary_area(
        self,
        boundary_geojson: Optional[Dict[str, Any]],
        landuse_projected: gpd.GeoDataFrame,
    ) -> float:
        """Compute total boundary area in square meters (projected CRS)."""
        if boundary_geojson:
            boundary_gdf = geojson_to_geodataframe(boundary_geojson)
            if boundary_gdf is not None:
                if boundary_gdf.crs and boundary_gdf.crs.is_geographic:
                    boundary_gdf = boundary_gdf.to_crs("EPSG:3857")
                return boundary_gdf.geometry.unary_union.area

        # Fallback: use convex hull of all projected parcels
        return landuse_projected.geometry.unary_union.convex_hull.area

    def _geometry_to_dict(self, geometry) -> Dict[str, Any]:
        """Convert a Shapely geometry to GeoJSON geometry dict."""
        geo_interface = geometry.__geo_interface__
        return {
            "type": geo_interface["type"],
            "coordinates": geo_interface["coordinates"],
        }


__all__ = ["ZoneGenerator", "resolve_zone_type_for_dlbm", "_EXTENDED_DLBM_TO_ZONE_TYPE"]
