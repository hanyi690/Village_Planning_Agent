"""Dynamic zoning engine based on double evaluation (双评价).

Implements resource environment carrying capacity + development suitability
evaluation per natural resource department guidelines (自然资源部《双评价指南》2019).

Decision rules for dynamic zone adjustment:
  1. Geological hazard 500m buffer → construction zones demoted to 生态控制区
  2. Ecological redline overlap → forced 生态保护区
  3. Basic farmland overlap → forced 农田保护区

Default mode (no evaluation data): pure DLBM static mapping (backward compatible).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from app.utils.logger import get_logger

logger = get_logger(__name__)

# ── Code sets from schema (single source of truth) ──
from app.modules.schema.encodings.code_sets import (
    BASIC_FARMLAND_CODES,
    FOREST_CODES,
    WATER_CODES,
    ECOLOGICAL_PROTECTION_CODES,
)
# Late imports for functions (avoid circular dependency)
_dlbm_to_planning_zone = None
_get_primary_zone_for_planning_zone = None

def _ensure_funcs():
    global _dlbm_to_planning_zone, _get_primary_zone_for_planning_zone
    if _dlbm_to_planning_zone is None:
        from app.modules.schema.advisory_crosswalks import (
            dlbm_to_planning_zone as _dpz,
            get_primary_zone_for_planning_zone as _gppz,
        )
        _dlbm_to_planning_zone = _dpz
        _get_primary_zone_for_planning_zone = _gppz

# Default buffer distance (meters) for geological hazard influence
GEOLOGICAL_HAZARD_BUFFER_M = 500.0


class DynamicZoningEngine:
    """Based on double evaluation results, dynamically adjusts parcel zones.

    Two modes:
      1. Default: pure DLBM static mapping (no evaluation data)
      2. Double evaluation: combines hazard/protection/distance factors

    Evaluation factors (using Jin Tian data):
      - Geological hazard density (geological_hazard_geojson, 40 points)
      - Protection area overlap (farmland/ecological/historical protection)
      - Road proximity (road_geojson, 131 roads)
    """

    def __init__(
        self,
        hazard_geojson: Optional[Dict[str, Any]] = None,
        ecological_protection_geojson: Optional[Dict[str, Any]] = None,
        farmland_protection_geojson: Optional[Dict[str, Any]] = None,
        historical_protection_geojson: Optional[Dict[str, Any]] = None,
        road_geojson: Optional[Dict[str, Any]] = None,
    ):
        self.hazard_points = self._extract_points(hazard_geojson)
        self.ecological_protection = ecological_protection_geojson
        self.farmland_protection = farmland_protection_geojson
        self.historical_protection = historical_protection_geojson
        self.road_geojson = road_geojson

        self._hazard_buffers: Optional[List[Tuple[float, float, float]]] = None

    @staticmethod
    def _extract_points(geojson: Optional[Dict[str, Any]]) -> List[Tuple[float, float]]:
        """Extract Point coordinates from GeoJSON."""
        if not geojson or not geojson.get("features"):
            return []
        points = []
        for feat in geojson["features"]:
            geom = feat.get("geometry", {})
            if geom.get("type") == "Point" and geom.get("coordinates"):
                coords = geom["coordinates"]
                points.append((coords[0], coords[1]))
        return points

    def _get_hazard_buffers(self) -> List[Tuple[float, float, float]]:
        """Pre-compute hazard point buffers as (lon, lat, buffer_degrees)."""
        if self._hazard_buffers is not None:
            return self._hazard_buffers

        if not self.hazard_points:
            self._hazard_buffers = []
            return self._hazard_buffers

        # Convert 500m to degrees at given latitude
        # 1° latitude ≈ 110.6km, 1° longitude ≈ 110.6km × cos(lat)
        import math
        buffers = []
        for lon, lat in self.hazard_points:
            lat_rad = math.radians(lat)
            m_per_deg_lat = 110600.0
            m_per_deg_lon = 110600.0 * math.cos(lat_rad)
            buf_lat = GEOLOGICAL_HAZARD_BUFFER_M / m_per_deg_lat
            buf_lon = GEOLOGICAL_HAZARD_BUFFER_M / m_per_deg_lon
            buffers.append((lon, lat, buf_lon, buf_lat))

        self._hazard_buffers = buffers
        return self._hazard_buffers

    def _is_near_hazard(self, lon: float, lat: float) -> bool:
        """Check if a point is within 500m of any geological hazard point."""
        buffers = self._get_hazard_buffers()
        if not buffers:
            return False
        for h_lon, h_lat, buf_lon, buf_lat in buffers:
            if abs(lon - h_lon) <= buf_lon and abs(lat - h_lat) <= buf_lat:
                return True
        return False

    def classify_parcel(
        self,
        dlbm: str,
        lon: Optional[float] = None,
        lat: Optional[float] = None,
        in_ecological_redline: bool = False,
        in_basic_farmland: bool = False,
    ) -> str:
        """Classify a single parcel into a planning zone.

        Decision priority (higher = overrides):
          1. Ecological redline overlap → 生态保护区 (forced)
          2. Basic farmland overlap → 农田保护区 (forced)
          3. Geological hazard buffer → construction demoted to 生态控制区
          4. DLBM static mapping (default)
        """
        _ensure_funcs()
        base_zone = _dlbm_to_planning_zone(dlbm)

        # Rule 1: Ecological redline forces 生态保护区 for construction zones
        if in_ecological_redline:
            if base_zone == "村庄建设区":
                return "生态保护区"

        # Rule 2: Basic farmland forces 农田保护区
        if in_basic_farmland and dlbm in BASIC_FARMLAND_CODES:
            return "农田保护区"

        # Rule 3: Hazard buffer demotes construction to 生态控制区
        if lon is not None and lat is not None and self._is_near_hazard(lon, lat):
            if base_zone == "村庄建设区":
                return "生态控制区"

        return base_zone

    def classify_geojson(
        self,
        geojson: Dict[str, Any],
        protection_zones: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Classify all parcels in a GeoJSON FeatureCollection.

        Updates zone_type for each feature based on dynamic rules.
        Returns the modified GeoJSON (in-place).
        """
        try:
            from shapely.geometry import shape
            from shapely.ops import unary_union
            HAS_SHAPELY = True
        except ImportError:
            HAS_SHAPELY = False

        # Pre-compute protection zone unions
        eco_union = None
        farm_union = None
        if HAS_SHAPELY and protection_zones:
            if "ecological" in protection_zones:
                eco_union = self._compute_union(protection_zones["ecological"])
            if "farmland" in protection_zones:
                farm_union = self._compute_union(protection_zones["farmland"])

        for feat in geojson.get("features", []):
            props = feat.get("properties", {})
            dlbm = str(props.get("DLBM", props.get("QMDLBM", ""))).strip()
            if not dlbm:
                continue

            # Extract centroid
            lon, lat = None, None
            in_eco_redline = False
            in_basic_farmland = False

            geom = feat.get("geometry", {})
            if HAS_SHAPELY and geom and geom.get("coordinates"):
                try:
                    shp = shape(geom)
                    centroid = shp.centroid
                    lon, lat = centroid.x, centroid.y

                    # Check protection overlaps
                    if eco_union is not None:
                        in_eco_redline = shp.intersects(eco_union)
                    if farm_union is not None:
                        in_basic_farmland = shp.intersects(farm_union)
                except Exception:
                    pass

            zone = self.classify_parcel(
                dlbm, lon, lat, in_eco_redline, in_basic_farmland
            )
            _ensure_funcs()
            props["zone_type"] = zone
            props["primary_zone"] = _get_primary_zone_for_planning_zone(zone)

        return geojson

    @staticmethod
    def _compute_union(geojson: Dict[str, Any]):
        """Compute unary union of all features in a GeoJSON."""
        from shapely.geometry import shape
        from shapely.ops import unary_union

        geoms = []
        for feat in geojson.get("features", []):
            g = feat.get("geometry", {})
            if g and g.get("coordinates"):
                try:
                    geoms.append(shape(g))
                except Exception:
                    continue
        if not geoms:
            return None
        return unary_union(geoms)
