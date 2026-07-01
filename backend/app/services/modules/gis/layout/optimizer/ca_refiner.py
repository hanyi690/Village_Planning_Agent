"""ZoneCARefiner — Cellular Automata-style spatial refinement.

Merges adjacent same-type parcels and simplifies boundaries to reduce
fragmented zoning outputs. Stage B of the three-stage spatial generator
pipeline (MIP allocation → CA refinement → facility/axis).

Algorithm:
  1. Group features by zone_type
  2. Buffer-union-debuffer same-type features to close small gaps
  3. Simplify merged boundaries (preserve topology)
  4. Validate area conservation after each iteration
"""

from __future__ import annotations

from typing import Any, Dict, List

from app.utils.logger import get_logger
from ...utils.geojson_utils import geojson_to_geodataframe
from ...utils.crs_engine import project_to_metric, project_to_wgs84, get_metric_crs
from ...utils.area_engine import calculate_area_ha
from ...utils.geo_utils import safe_unary_union

logger = get_logger(__name__)

try:
    import geopandas as gpd
    import shapely

    SHAPELY_AVAILABLE = True
except ImportError:
    SHAPELY_AVAILABLE = False
    logger.warning("[ca_refiner] shapely/geopandas not available")


class ZoneCARefiner:
    """Refine zone features by merging adjacent same-type parcels.

    Uses buffer-union-debuffer to close gaps < merge_distance_m between
    same-type features, then simplifies boundaries.
    """

    def __init__(
        self,
        merge_distance_m: float = 30.0,
        simplify_tolerance_m: float = 10.0,
        iterations: int = 3,
        min_area_ha: float = 0.5,
    ) -> None:
        if not SHAPELY_AVAILABLE:
            raise RuntimeError("shapely/geopandas required for ZoneCARefiner")
        self.merge_distance_m = merge_distance_m
        self.simplify_tolerance_m = simplify_tolerance_m
        self.iterations = iterations
        self.min_area_ha = min_area_ha

    def refine(self, features: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not features:
            return features

        original_area = self._total_area_ha(features)

        result_features = list(features)

        for iteration in range(self.iterations):
            # Rebuild by_type each iteration to avoid stale indices after merge
            by_type_iter: Dict[str, List[int]] = {}
            for i, f in enumerate(result_features):
                zt = (
                    f.get("properties", {}).get("assigned_zone")
                    or f.get("properties", {}).get("zone_type")
                    or f.get("properties", {}).get("land_use", "unknown")
                )
                by_type_iter.setdefault(zt, []).append(i)

            prev_count = sum(1 for f in result_features if f.get("geometry", {}).get("coordinates"))
            result_features = self._merge_pass(result_features, by_type_iter)
            curr_count = sum(1 for f in result_features if f.get("geometry", {}).get("coordinates"))

            if curr_count >= prev_count:
                logger.info(f"[CARefiner] Iteration {iteration + 1}: no merging, stopping")
                break

            logger.info(f"[CARefiner] Iteration {iteration + 1}: {prev_count} → {curr_count}")

        final_area = self._total_area_ha(result_features)
        area_loss_pct = abs(original_area - final_area) / max(original_area, 1) * 100

        if area_loss_pct > 2.0:
            logger.warning(f"[CARefiner] Area loss {area_loss_pct:.1f}% ({original_area:.1f} → {final_area:.1f} ha)")
        else:
            logger.info(f"[CARefiner] Area conserved: {original_area:.1f} → {final_area:.1f} ha ({area_loss_pct:.2f}%)")

        return result_features

    def _merge_pass(
        self, features: List[Dict[str, Any]], by_type: Dict[str, List[int]]
    ) -> List[Dict[str, Any]]:
        processed = set()
        result = []

        for zone_type, indices in by_type.items():
            type_geoms_4326 = []
            type_props = []

            for idx in indices:
                if idx in processed:
                    continue
                f = features[idx]
                geom = _feature_to_shapely(f)
                if geom is None or geom.is_empty:
                    result.append(f)
                    processed.add(idx)
                    continue

                type_geoms_4326.append(geom)
                type_props.append(f.get("properties", {}))
                processed.add(idx)

            if not type_geoms_4326:
                continue

            if len(type_geoms_4326) == 1:
                result.append(_shapely_to_feature(type_geoms_4326[0], type_props[0]))
                continue

            try:
                merged = self._buffer_union_debuffer(type_geoms_4326)
            except Exception as e:
                logger.warning(f"[CARefiner] Merge failed for {zone_type}: {e}")
                for geom, props in zip(type_geoms_4326, type_props):
                    result.append(_shapely_to_feature(geom, props))
                continue

            if merged is None or merged.is_empty:
                for geom, props in zip(type_geoms_4326, type_props):
                    result.append(_shapely_to_feature(geom, props))
                continue

            rep_props = type_props[0].copy()
            rep_props["area_ha"] = round(sum(p.get("area_ha", 0) for p in type_props), 2)
            rep_props["parcel_count"] = sum(p.get("parcel_count", 1) for p in type_props)
            rep_props["ca_merged"] = True

            result.append(_shapely_to_feature(merged, rep_props))

        for i, f in enumerate(features):
            if i not in processed:
                result.append(f)

        return result

    def _buffer_union_debuffer(self, geoms_4326):
        """Buffer → union → debuffer to close gaps < merge_distance_m."""
        gs = gpd.GeoSeries(geoms_4326, crs="EPSG:4326")
        gs_m = project_to_metric(gs)
        geoms_m = list(gs_m)
        metric_crs = gs_m.crs
        original_area_m = sum(g.area for g in geoms_m if not g.is_empty)

        buffered = [g.buffer(self.merge_distance_m) for g in geoms_m if not g.is_empty]
        if not buffered:
            return None

        unioned = safe_unary_union(buffered)
        if unioned.is_empty:
            return None

        debuffered = unioned.buffer(-self.merge_distance_m)
        if debuffered.is_empty:
            debuffered = unioned

        simplified = debuffered.simplify(self.simplify_tolerance_m, preserve_topology=True)

        # Remove sliver polygons below min_area threshold
        if hasattr(simplified, "geoms"):
            kept = [g for g in simplified.geoms if g.area / 10000 >= self.min_area_ha]
            if kept and len(kept) < len(list(simplified.geoms)):
                from shapely.geometry import MultiPolygon
                simplified = MultiPolygon(kept) if len(kept) > 1 else kept[0]

        # Record area deviation for engine validation feedback (no geometric compensation)
        result_area_m = simplified.area
        if result_area_m > 0 and original_area_m > 0:
            loss_ratio = abs(original_area_m - result_area_m) / original_area_m
            if loss_ratio > 0.005:
                logger.info(
                    f"[CARefiner] Area deviation {loss_ratio*100:.1f}% "
                    f"({original_area_m/10000:.1f} -> {result_area_m/10000:.1f} ha), "
                    f"handled by engine validation"
                )

        return project_to_wgs84(gpd.GeoSeries([simplified], crs=metric_crs)).iloc[0]

    def _total_area_ha(self, features: List[Dict[str, Any]]) -> float:
        """Compute total area via batch GeoDataFrame conversion (avoids per-feature CRS)."""
        gdf = geojson_to_geodataframe({"type": "FeatureCollection", "features": features})
        if gdf is None or gdf.empty:
            return sum(f.get("properties", {}).get("area_ha", 0) for f in features)
        gdf_m = project_to_metric(gdf)
        return gdf_m.geometry.area.sum() / 10000


def _feature_to_shapely(feature: Dict[str, Any]):
    """Convert a GeoJSON feature dict to a Shapely geometry."""
    import shapely.geometry
    geom_dict = feature.get("geometry", {})
    if not geom_dict or not geom_dict.get("coordinates"):
        return None
    try:
        return shapely.geometry.shape(geom_dict)
    except Exception:
        return None


def _shapely_to_feature(geometry, properties: Dict[str, Any]) -> Dict[str, Any]:
    """Convert a Shapely geometry to a GeoJSON feature dict with recalculated area."""
    # make_valid may return GeometryCollection; extract polygons
    if geometry.geom_type == "GeometryCollection":
        polygons = [g for g in geometry.geoms if g.geom_type in ("Polygon", "MultiPolygon")]
        if not polygons:
            return None
        from shapely.ops import unary_union as _unary_union
        geometry = _unary_union(polygons)

    geo_iface = geometry.__geo_interface__
    try:
        properties = {**properties, "area_ha": round(calculate_area_ha(geometry), 2)}
    except Exception:
        pass

    return {
        "type": "Feature",
        "properties": properties,
        "geometry": {"type": geo_iface["type"], "coordinates": geo_iface["coordinates"]},
    }


__all__ = ["ZoneCARefiner"]
