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

import functools
import uuid
from typing import Any, Dict, List, Optional, Tuple

from app.utils.logger import get_logger
from app.modules.schema.contracts.parse_contracts import ZoneTarget
from app.modules.schema import (
    get_zone_color,
    get_zone_type_for_dlbm,
    resolve_zone_type_for_dlbm,
    get_dlbms_for_zone_type,
    ZONE_TYPE_COLORS,
)

logger = get_logger(__name__)

try:
    import geopandas as gpd
    import shapely.geometry as geom
    from shapely.ops import unary_union as _unary_union
    GEOPANDAS_AVAILABLE = True
except ImportError:
    GEOPANDAS_AVAILABLE = False
    logger.warning("[zone_generator] geopandas/shapely not available")

from app.utils.geojson_utils import geojson_to_geodataframe, geodataframe_to_geojson
from app.utils.crs_engine import project_to_metric, project_to_wgs84, get_metric_crs
from app.utils.geo_utils import safe_unary_union, safe_geo_series_union
from app.utils.area_engine import calculate_area_ha


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
        zones: List[ZoneTarget],
        boundary_geojson: Optional[Dict[str, Any]] = None,
        landuse_current_geojson: Optional[Dict[str, Any]] = None,
        protection_zones: Optional[Dict[str, Dict[str, Any]]] = None,
        enable_ca_refinement: bool = True,
    ) -> Dict[str, Any]:
        """Generate function_zone GeoJSON from ZoneTarget list.

        Args:
            zones: List of ZoneTarget from PARSE SpatialPlanningIntent
            boundary_geojson: Village boundary GeoJSON
            landuse_current_geojson: Current land use parcels GeoJSON
            protection_zones: Optional dict of protection zone GeoJSONs
            enable_ca_refinement: Enable CA-based merge refinement

        Returns:
            GeoJSON FeatureCollection with function_zone features
        """
        if not zones:
            logger.warning("[ZoneGenerator] No zones in intent")
            return {"type": "FeatureCollection", "features": []}

        if not landuse_current_geojson:
            logger.warning("[ZoneGenerator] No landuse_current data provided")
            return self._generate_from_intent_only(zones, boundary_geojson)

        # Load reference data (keep original CRS for geometry output)
        landuse_gdf = geojson_to_geodataframe(landuse_current_geojson)
        if landuse_gdf is None:
            logger.warning("[ZoneGenerator] Failed to load landuse_current")
            return self._generate_from_intent_only(zones, boundary_geojson)

        # Project to metric CRS for area calculations only
        if landuse_gdf.crs and landuse_gdf.crs.is_geographic:
            landuse_projected = project_to_metric(landuse_gdf)
        else:
            landuse_projected = landuse_gdf

        boundary_area_sqm = self._compute_boundary_area(boundary_geojson, landuse_projected)

        # Classify parcels by zone type (includes extended DLBM mapping)
        parcel_zones = self._classify_parcels(landuse_gdf)

        # Build zone features
        features = []
        for zone_intent in zones:
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
            features, landuse_gdf, landuse_projected
        )

        # CA refinement: merge adjacent same-type parcels
        if enable_ca_refinement:
            try:
                from app.tools.gis._generation.optimizer.ca_refiner import ZoneCARefiner
                ca = ZoneCARefiner(
                    merge_distance_m=30,
                    simplify_tolerance_m=10,
                    iterations=3,
                    min_area_ha=0.5,
                )
                features = ca.refine(features)
            except Exception as e:
                logger.warning(f"[ZoneGenerator] CA refinement failed: {e}, skipping")

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
        zone_intent: ZoneTarget,
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

        merged = safe_unary_union(geometries)

        if merged.is_empty:
            return None

        # Area from projected CRS for accurate measurement
        matched_projected = landuse_projected.loc[parcel_indices]
        projected_geoms = [g for g in matched_projected.geometry if g is not None and not g.is_empty]
        if projected_geoms:
            current_area_sqm = safe_unary_union(projected_geoms).area
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
                "direction": zone_intent.spatial_preference.direction if zone_intent.spatial_preference else "center",
                "density": zone_intent.density,
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

            merged = safe_unary_union(geometries)
            if merged.is_empty:
                continue

            # Area from projected CRS
            matched_projected = landuse_projected.loc[indices]
            projected_geoms = [g for g in matched_projected.geometry if g is not None and not g.is_empty]
            area_sqm = safe_unary_union(projected_geoms).area if projected_geoms else 0.0
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
            import shapely.geometry
            import shapely.geometry
        except ImportError:
            return features

        logger.info("[ZoneGenerator] Applying planning geometry transforms")

        # Determine metric CRS once for all transforms
        metric_crs = None
        for f in features:
            geom_dict = f.get("geometry", {})
            if geom_dict and geom_dict.get("coordinates"):
                try:
                    g = shapely.geometry.shape(geom_dict)
                    if not g.is_empty:
                        metric_crs = get_metric_crs(g.centroid.x)
                        break
                except Exception:
                    continue
        if metric_crs is None:
            return features

        # Group features by zone type for merge-nearby
        by_zone: Dict[str, List[int]] = {}
        for i, f in enumerate(features):
            zt = f["properties"].get("land_use", "")
            by_zone.setdefault(zt, []).append(i)

        # Batch-precompute metric geometries and WGS-84 originals for all features
        geoms_wgs84 = []
        geoms_metric = []
        valid_indices = []
        for i, f in enumerate(features):
            geom_dict = f.get("geometry", {})
            if not geom_dict or not geom_dict.get("coordinates"):
                geoms_wgs84.append(None)
                geoms_metric.append(None)
                continue
            try:
                g = shapely.geometry.shape(geom_dict)
                if g.is_empty:
                    geoms_wgs84.append(None)
                    geoms_metric.append(None)
                    continue
                geoms_wgs84.append(g)
                geoms_metric.append(None)  # placeholder, filled by batch CRS
                valid_indices.append(i)
            except Exception:
                geoms_wgs84.append(None)
                geoms_metric.append(None)

        # Batch CRS conversion: project all valid geometries at once
        if valid_indices:
            batch_gs = gpd.GeoSeries([geoms_wgs84[i] for i in valid_indices], crs="EPSG:4326")
            batch_gs_m = project_to_metric(batch_gs)
            # Map back to indices
            metric_map = {}
            for k, idx in enumerate(valid_indices):
                metric_map[idx] = batch_gs_m.iloc[k]
                geoms_metric[idx] = batch_gs_m.iloc[k]

        expand_types = {"居住用地", "产业用地", "公共服务用地"}
        simplify_tolerance = 10  # meters
        merge_distance = 20  # meters - merge parcels within this distance

        for i, feature in enumerate(features):
            geom = geoms_wgs84[i]
            if geom is None:
                continue

            zone_type = feature["properties"].get("land_use", "")

            # 1. Expand construction zones slightly
            if zone_type in expand_types:
                geom_m = geoms_metric[i]
                if geom_m is not None:
                    expanded = geom_m.buffer(0.5)
                    geom = project_to_wgs84(gpd.GeoSeries([expanded], crs=metric_crs))[0]

            # 2. Simplify boundaries for all zones
            geom_m = geoms_metric[i]
            if geom_m is not None:
                simplified = geom_m.simplify(simplify_tolerance, preserve_topology=True)
                geom = project_to_wgs84(gpd.GeoSeries([simplified], crs=metric_crs))[0]

            # Update geometry
            geo_iface = geom.__geo_interface__
            feature["geometry"] = {
                "type": geo_iface["type"],
                "coordinates": geo_iface["coordinates"],
            }

            # 3. Recalculate area (use metric_crs fast path when geom_m available)
            if geom_m is not None:
                area_ha = calculate_area_ha(geom_m, metric_crs=metric_crs)
            else:
                area_ha = calculate_area_ha(geom)
            feature["properties"]["area_ha"] = round(area_ha, 2)
            feature["properties"]["transformed"] = True

        # 4. Merge nearby parcels of same zone type within merge_distance
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

            geom_i_m = geoms_metric[i]
            if geom_i_m is None:
                merged_features.append(feature)
                processed.add(i)
                continue

            merge_group = [i]

            for j in same_type:
                if j <= i or j in processed:
                    continue
                geom_j_m = geoms_metric[j]
                if geom_j_m is None:
                    continue
                dist = geom_i_m.distance(geom_j_m)
                if dist < merge_distance:
                    merge_group.append(j)

            if len(merge_group) > 1:
                geoms_m = [geoms_metric[idx] for idx in merge_group if geoms_metric[idx] is not None]
                merged_m = safe_unary_union(geoms_m)
                merged_4326 = project_to_wgs84(gpd.GeoSeries([merged_m], crs=metric_crs))[0]
                total_area_ha = calculate_area_ha(merged_m, metric_crs=metric_crs)
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

        Uses shapely.difference() to subtract protection areas from each
        zone feature, ensuring basic farmland / ecological redlines are
        not encroached upon by construction or other zones.
        """
        if not protection_zones:
            return features

        # Build a merged protection MultiPolygon in metric CRS
        protection_geoms_m = []
        metric_crs = None
        for zone_name, protection_geojson in protection_zones.items():
            if not protection_geojson or not protection_geojson.get("features"):
                continue
            try:
                pgdf = geojson_to_geodataframe(protection_geojson)
                if pgdf is None or pgdf.empty:
                    continue
                pgdf_m = project_to_metric(pgdf)
                if metric_crs is None:
                    metric_crs = pgdf_m.crs
                protection_geoms_m.append(safe_geo_series_union(pgdf_m.geometry))
            except Exception as e:
                logger.warning(
                    f"[ZoneGenerator] Failed to load protection zone "
                    f"'{zone_name}': {e}"
                )

        if not protection_geoms_m:
            logger.info("[ZoneGenerator] No valid protection geometries to apply")
            return features

        protection_multi_m = safe_unary_union(protection_geoms_m)

        if protection_multi_m.is_empty:
            return features

        # Determine metric CRS from protection zone if not already set
        if metric_crs is None:
            metric_crs = get_metric_crs(protection_multi_m.centroid.x)

        # Batch-convert all feature geometries to metric CRS (avoids N+1 CRS conversions)
        valid_indices = []
        geoms_4326_list = []
        for i, feature in enumerate(features):
            geom_dict = feature.get("geometry", {})
            if not geom_dict or not geom_dict.get("coordinates"):
                continue
            try:
                geom = shapely.geometry.shape(geom_dict)
                if not geom.is_empty:
                    valid_indices.append(i)
                    geoms_4326_list.append(geom)
            except Exception:
                continue

        if not geoms_4326_list:
            return features

        # Single batch CRS conversion for all features
        geoms_m_series = gpd.GeoSeries(geoms_4326_list, crs="EPSG:4326").to_crs(metric_crs)

        total_removed_ha = 0.0
        result_features = list(features)  # copy to mutate

        for batch_idx, feat_idx in enumerate(valid_indices):
            feature = features[feat_idx]
            geom_m = geoms_m_series.iloc[batch_idx]
            area_before = calculate_area_ha(geom_m, metric_crs=metric_crs)

            try:
                clipped_m = geom_m.difference(protection_multi_m)

                if clipped_m.is_empty:
                    total_removed_ha += area_before
                    logger.info(
                        f"[ZoneGenerator] Feature "
                        f"'{feature['properties'].get('zone_id', '?')}' "
                        f"fully removed by protection ({area_before:.2f} ha)"
                    )
                    result_features[feat_idx] = None  # mark for removal
                    continue

                area_after = calculate_area_ha(clipped_m, metric_crs=metric_crs)
                total_removed_ha += area_before - area_after

                clipped_4326 = project_to_wgs84(
                    gpd.GeoSeries([clipped_m], crs=metric_crs)
                )[0]

                geo_iface = clipped_4326.__geo_interface__
                result_features[feat_idx] = dict(feature)
                result_features[feat_idx]["geometry"] = {
                    "type": geo_iface["type"],
                    "coordinates": geo_iface["coordinates"],
                }
                result_features[feat_idx]["properties"] = dict(feature["properties"])
                result_features[feat_idx]["properties"]["area_ha"] = round(area_after, 2)
                result_features[feat_idx]["properties"]["protection_clipped"] = True

            except Exception as e:
                logger.warning(
                    f"[ZoneGenerator] Subtraction failed for "
                    f"'{feature.get('properties', {}).get('zone_id', '?')}': {e}"
                )

        # Filter out removed features (marked as None)
        result_features = [f for f in result_features if f is not None]

        logger.info(
            f"[ZoneGenerator] Protection constraints: "
            f"{len(features)} → {len(result_features)} features, "
            f"{total_removed_ha:.1f} ha removed"
        )
        return result_features

    def _generate_from_intent_only(
        self,
        zones: List[ZoneTarget],
        boundary_geojson: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Fallback: generate placeholder zones without reference data."""
        features = []
        for zone_intent in zones:
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
                    "direction": zone_intent.spatial_preference.direction if zone_intent.spatial_preference else "center",
                    "density": zone_intent.density,
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
                    boundary_gdf = project_to_metric(boundary_gdf)
                return safe_geo_series_union(boundary_gdf.geometry).area

        # Fallback: use convex hull of all projected parcels
        return safe_geo_series_union(landuse_projected.geometry).convex_hull.area

    def _geometry_to_dict(self, geometry) -> Dict[str, Any]:
        """Convert a Shapely geometry to GeoJSON geometry dict."""
        # make_valid may return GeometryCollection; extract largest polygon
        if geometry.geom_type == "GeometryCollection":
            polygons = [g for g in geometry.geoms if g.geom_type in ("Polygon", "MultiPolygon")]
            if not polygons:
                return {"type": "Polygon", "coordinates": []}
            from shapely.ops import unary_union as _unary_union
            geometry = _unary_union(polygons)

        geo_interface = geometry.__geo_interface__
        return {
            "type": geo_interface["type"],
            "coordinates": geo_interface["coordinates"],
        }


__all__ = ["ZoneGenerator", "resolve_zone_type_for_dlbm"]
