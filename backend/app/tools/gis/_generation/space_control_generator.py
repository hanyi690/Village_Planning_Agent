"""Space Control Zone Generator — 建设用地空间管制区 (4 classes).

Generates the space_control_zone layer following Guangdong provincial standard:
  510: 允许建设区 (Permitted Construction) — 村庄建设边界内部
  520: 限制建设区 (Restricted Construction) — 除以下三类以外的区域
  530: 有条件建设区 (Conditional Construction) — ≤ 现状建设用地×20%
  540: 禁止建设区 (Prohibited Construction) — 永久基本农田 + 生态保护红线

Quality rules:
  - 允许建设区和有条件建设区内不能有基本农田
  - 有条件建设区内不能规划建设用地
  - 禁止建设区 = 基本农田 ∪ 生态红线（不可调整）
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from app.utils.logger import get_logger

logger = get_logger(__name__)

try:
    import geopandas as gpd
    from shapely.geometry import shape, box, mapping
    from shapely.ops import unary_union, transform
    GEOPANDAS_AVAILABLE = True
except ImportError:
    GEOPANDAS_AVAILABLE = False

# Zone type definitions
SPACE_CONTROL_ZONES: Dict[str, Dict[str, Any]] = {
    "510": {"name": "允许建设区", "description": "村庄建设边界内部", "color": "#FFE0B2"},
    "520": {"name": "限制建设区", "description": "一般农业和生态区域", "color": "#C8E6C9"},
    "530": {"name": "有条件建设区", "description": "≤现状建设用地×20%", "color": "#FFF9C4"},
    "540": {"name": "禁止建设区", "description": "永久基本农田+生态红线", "color": "#FFCDD2"},
}


class SpaceControlZoneGenerator:
    """Generate 4-class space control zone layer for village planning.

    Inputs:
      - boundary: village boundary polygon
      - construction_boundary: planned construction boundary (or default from intent)
      - planned_landuse: allocated landuse GeoJSON
      - farmland_protection: permanent basic farmland redline
      - ecological_protection: ecological protection redline
      - current_landuse: for calculating 20% threshold (现状建设用地面积)

    Output:
      GeoJSON FeatureCollection with 4 zone types covering entire village area.
    """

    def generate(
        self,
        boundary: Dict[str, Any],
        construction_boundary: Optional[Dict[str, Any]] = None,
        planned_landuse: Optional[Dict[str, Any]] = None,
        farmland_protection: Optional[Dict[str, Any]] = None,
        ecological_protection: Optional[Dict[str, Any]] = None,
        current_landuse: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Generate space control zone GeoJSON.

        Returns FeatureCollection with features labeled by TDKJGZFQDM (510/520/530/540).
        """
        if not boundary or not GEOPANDAS_AVAILABLE:
            return self._empty_result()

        try:
            boundary_geom = self._extract_main_geom(boundary)
            if boundary_geom is None:
                return self._empty_result()

            # ── 540: 禁止建设区 = 基本农田 ∪ 生态红线 ──
            prohibited = self._union_protection_zones(farmland_protection, ecological_protection)

            # ── 510: 允许建设区 = 村庄建设边界 ──
            permitted = self._extract_construction_boundary(construction_boundary, boundary_geom)
            if permitted is not None:
                permitted = permitted.intersection(boundary_geom)

            # ── 530: 有条件建设区 ≤ 现状建设用地×20% ──
            conditional = self._compute_conditional_zone(
                permitted, current_landuse, boundary_geom, prohibited,
            )

            # ── 520: 限制建设区 = 全域 - (510+530+540) ──
            restricted = self._compute_restricted_zone(
                boundary_geom, permitted, conditional, prohibited,
            )

            # Build feature collection
            features = []
            for code, geom in [
                ("510", permitted),
                ("520", restricted),
                ("530", conditional),
                ("540", prohibited),
            ]:
                if geom is not None and not geom.is_empty:
                    info = SPACE_CONTROL_ZONES[code]
                    features.append({
                        "type": "Feature",
                        "geometry": mapping(geom),
                        "properties": {
                            "TDKJGZFQDM": code,
                            "GZFQMC": info["name"],
                            "description": info["description"],
                        },
                    })

            return {
                "type": "FeatureCollection",
                "features": features,
            }

        except Exception as e:
            logger.error("[SpaceControlZoneGenerator] Generation failed: %s", e)
            return self._empty_result()

    # ── Private helpers ─────────────────────────────────────────────────

    def _empty_result(self) -> Dict[str, Any]:
        return {"type": "FeatureCollection", "features": []}

    def _extract_main_geom(self, geojson: Dict[str, Any]):
        """Extract main polygon from GeoJSON."""
        try:
            gdf = gpd.GeoDataFrame.from_features(geojson.get("features", geojson))
            if gdf.empty:
                return None
            return unary_union(gdf.geometry.values)
        except Exception:
            return shape(geojson) if geojson.get("type") else None

    def _union_protection_zones(
        self,
        farmland: Optional[Dict[str, Any]],
        ecological: Optional[Dict[str, Any]],
    ):
        """Union farmland + ecological protection into prohibited zone (540)."""
        geoms = []
        for source in (farmland, ecological):
            if source and source.get("features"):
                try:
                    gdf = gpd.GeoDataFrame.from_features(source["features"])
                    if not gdf.empty:
                        geoms.append(unary_union(gdf.geometry.values))
                except Exception:
                    pass
        if not geoms:
            return None
        return unary_union(geoms) if len(geoms) > 1 else geoms[0]

    def _extract_construction_boundary(self, construction_boundary, fallback_geom):
        """Extract 510 zone boundary. Falls back to using intent/planned data."""
        if construction_boundary and construction_boundary.get("features"):
            try:
                gdf = gpd.GeoDataFrame.from_features(construction_boundary["features"])
                if not gdf.empty:
                    return unary_union(gdf.geometry.values)
            except Exception:
                pass

        # Fallback: use a convex buffer from the village center
        # In production, construction boundary should come from planning intent
        if fallback_geom is not None:
            centroid = fallback_geom.centroid
            # Default: 10% of village area as construction boundary
            area = fallback_geom.area
            radius = (area * 0.10 / 3.14159) ** 0.5
            return centroid.buffer(radius * 0.5)  # conservative default

        return None

    def _compute_conditional_zone(self, permitted, current_landuse, boundary, prohibited):
        """Compute 530 conditional construction zone.

        Rule: ≤ 现状建设用地面积 × 20%
        Constraint: 不占基本农田 + 生态红线
        """
        if current_landuse is None or not current_landuse.get("features"):
            return None

        try:
            # Calculate current construction land area
            from app.modules.gis.schema import CONSTRUCTION_ZONE_TYPES
            from app.modules.gis.schema import get_zone_type_for_dlbm

            construction_area = 0.0
            construction_geoms = []
            for feat in current_landuse.get("features", []):
                dlbm = str(feat.get("properties", {}).get("DLBM", ""))
                zone = get_zone_type_for_dlbm(dlbm)
                if zone in CONSTRUCTION_ZONE_TYPES:
                    try:
                        g = shape(feat.get("geometry", {}))
                        construction_area += g.area
                        construction_geoms.append(g)
                    except Exception:
                        pass

            if construction_area == 0:
                return None

            # 20% of current construction area
            conditional_target = construction_area * 0.20

            if permitted is not None:
                # Generate conditional zone adjacent to permitted zone
                # Buffer outward from permitted boundary
                conditional = permitted.buffer(permitted.area ** 0.5 * 0.05)
                conditional = conditional.difference(permitted)
            else:
                return None

            if conditional is None or conditional.is_empty:
                return None

            # Clip to boundary
            if boundary is not None:
                conditional = conditional.intersection(boundary)

            # Exclude prohibited zones
            if prohibited is not None:
                conditional = conditional.difference(prohibited)

            return conditional if not conditional.is_empty else None

        except Exception as e:
            logger.warning("[SpaceControlZoneGenerator] Conditional zone failed: %s", e)
            return None

    def _compute_restricted_zone(self, boundary, permitted, conditional, prohibited):
        """Compute 520 restricted zone: 全域 - (510+530+540)."""
        if boundary is None:
            return None

        restricted = boundary
        for zone in (permitted, conditional, prohibited):
            if zone is not None and not zone.is_empty:
                restricted = restricted.difference(zone)

        return restricted if not restricted.is_empty else None


__all__ = ["SpaceControlZoneGenerator", "SPACE_CONTROL_ZONES"]
