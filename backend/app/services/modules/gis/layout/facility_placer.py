"""Facility placement module — rule-based facility point generation.

Maps FacilityIntent (from LLM) to GeoJSON Point features based on:
  - 现状保留: keep existing POI location
  - 规划新建: place at centroid of matching DLBM parcels + direction offset
  - 规划改扩建: keep existing location, expand service radius
  - 规划迁建: find nearest suitable parcel
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple

from app.utils.logger import get_logger

logger = get_logger(__name__)

# DLBM codes that are suitable for each facility type
FACILITY_DLBM_MAP = {
    "村委会": {"preferred": ["2122", "2125"], "acceptable": ["2121"]},
    "学校": {"preferred": ["2122"], "acceptable": ["2121"]},
    "卫生站": {"preferred": ["2122", "0800"], "acceptable": ["2121"]},
    "文化站": {"preferred": ["2122"], "acceptable": ["2121"]},
    "市场": {"preferred": ["0500"], "acceptable": ["2124"]},
    "养老服务": {"preferred": ["2122"], "acceptable": ["2121"]},
    "产业服务中心": {"preferred": ["2124"], "acceptable": ["2122"]},
    "停车场": {"preferred": ["2126"], "acceptable": ["2121"]},
}

# Default facility colors for rendering
FACILITY_COLORS = {
    "村委会": "#8B4513",
    "学校": "#4169E1",
    "卫生站": "#DC143C",
    "文化站": "#9932CC",
    "市场": "#FF8C00",
    "养老服务": "#2F4F4F",
    "产业服务中心": "#B8860B",
    "停车场": "#696969",
}

# Direction → offset in degrees (approximate, for placement near centroid)
DIRECTION_OFFSET = {
    "center": (0.0, 0.0),
    "north": (0.0, 0.003),
    "south": (0.0, -0.003),
    "east": (0.003, 0.0),
    "west": (-0.003, 0.0),
    "northeast": (0.002, 0.002),
    "northwest": (-0.002, 0.002),
    "southeast": (0.002, -0.002),
    "southwest": (-0.002, -0.002),
    "periphery": (0.004, 0.0),
}


class FacilityPlacer:
    """Rule-based facility placement from FacilityIntent list."""

    def place(
        self,
        facilities: List[Any],
        landuse_geojson: Optional[Dict[str, Any]] = None,
        boundary_geojson: Optional[Dict[str, Any]] = None,
        existing_pois: Optional[List[Dict[str, Any]]] = None,
        hazard_points_geojson: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Generate facility_point GeoJSON from FacilityIntent list.

        Args:
            facilities: List of FacilityIntent objects or dicts
            landuse_geojson: Current land use parcels (for centroid placement)
            boundary_geojson: Village boundary (for fallback centroid)
            existing_pois: Existing POI data from search_poi tool
            hazard_points_geojson: Geological hazard points (merged into output)

        Returns:
            GeoJSON FeatureCollection of facility Point features
        """
        features = []

        # Pre-compute parcel centroids if available
        parcel_centroids = self._compute_parcel_centroids(landuse_geojson)
        boundary_center = self._compute_boundary_center(boundary_geojson)

        for fac in facilities:
            # Convert dict to expected format if needed
            if isinstance(fac, dict):
                fac_id = fac.get("facility_id", "")
                fac_type = fac.get("facility_type", "")
                location_hint = fac.get("location_hint", "")
                status = fac.get("status", "现状保留")
                direction = fac.get("direction", "center")
            else:
                fac_id = fac.facility_id
                fac_type = fac.facility_type
                location_hint = fac.location_hint
                status = fac.status
                direction = getattr(fac, "direction", "center")

            point = None

            if status in ("现状保留", "existing"):
                point = self._place_existing(fac_type, existing_pois, parcel_centroids)
            elif status in ("规划新建", "planned"):
                point = self._place_new(fac_type, direction, parcel_centroids, boundary_center)
            elif status in ("规划改扩建", "upgraded"):
                point = self._place_upgraded(fac_type, existing_pois, parcel_centroids, boundary_center)
            elif status in ("规划迁建", "relocated"):
                point = self._place_relocated(fac_type, parcel_centroids, boundary_center)

            if point:
                color = FACILITY_COLORS.get(fac_type, "#666666")
                features.append({
                    "type": "Feature",
                    "properties": {
                        "facility_id": fac_id,
                        "facility_type": fac_type,
                        "status": status,
                        "location_hint": location_hint,
                        "color": color,
                        "service_radius": self._get_service_radius(fac_type, status),
                    },
                    "geometry": {
                        "type": "Point",
                        "coordinates": point,
                    },
                })
            else:
                logger.warning(f"[FacilityPlacer] Could not place facility: {fac_id} ({fac_type})")

        # Merge hazard points into facility_point layer
        if hazard_points_geojson and hazard_points_geojson.get("features"):
            for feat in hazard_points_geojson["features"]:
                feat = dict(feat)
                feat.setdefault("properties", {})
                feat["properties"]["facility_type"] = feat["properties"].get("hazard_type", "地质灾害点")
                feat["properties"]["status"] = "现状"
                feat["properties"]["color"] = "#FF0000"
                features.append(feat)

        if not features:
            return {"type": "FeatureCollection", "features": []}

        logger.info(f"[FacilityPlacer] Placed {len(features)} facility points")
        return {"type": "FeatureCollection", "features": features}

    def _place_existing(
        self,
        fac_type: str,
        existing_pois: Optional[List[Dict]],
        parcel_centroids: Dict[str, Tuple[float, float]],
    ) -> Optional[List[float]]:
        """Place existing facility — keep POI location or fall back to parcel centroid."""
        if existing_pois:
            for poi in existing_pois:
                if fac_type in poi.get("name", ""):
                    loc = poi.get("location", "")
                    if isinstance(loc, (list, tuple)) and len(loc) == 2:
                        return [float(loc[0]), float(loc[1])]

        # Fallback: centroid of preferred DLBM parcels
        pref_dlbms = FACILITY_DLBM_MAP.get(fac_type, {}).get("preferred", [])
        return self._centroid_of_dlbm(pref_dlbms, parcel_centroids)

    def _place_new(
        self,
        fac_type: str,
        direction: str,
        parcel_centroids: Dict[str, Tuple[float, float]],
        boundary_center: Optional[List[float]],
    ) -> Optional[List[float]]:
        """Place new facility — centroid of preferred DLBM + direction offset."""
        pref_dlbms = FACILITY_DLBM_MAP.get(fac_type, {}).get("preferred", [])
        centroid = self._centroid_of_dlbm(pref_dlbms, parcel_centroids)

        if centroid is None:
            centroid = boundary_center

        if centroid is None:
            return None

        # Apply direction offset
        offset = DIRECTION_OFFSET.get(str(direction), (0.0, 0.0))
        return [centroid[0] + offset[0], centroid[1] + offset[1]]

    def _place_upgraded(
        self,
        fac_type: str,
        existing_pois: Optional[List[Dict]],
        parcel_centroids: Dict[str, Tuple[float, float]],
        boundary_center: Optional[List[float]],
    ) -> Optional[List[float]]:
        """Place upgraded facility — same location as existing."""
        return self._place_existing(fac_type, existing_pois, parcel_centroids)

    def _place_relocated(
        self,
        fac_type: str,
        parcel_centroids: Dict[str, Tuple[float, float]],
        boundary_center: Optional[List[float]],
    ) -> Optional[List[float]]:
        """Place relocated facility — find nearest suitable parcel centroid."""
        all_dlbms = []
        fac_map = FACILITY_DLBM_MAP.get(fac_type, {})
        all_dlbms.extend(fac_map.get("preferred", []))
        all_dlbms.extend(fac_map.get("acceptable", []))

        centroid = self._centroid_of_dlbm(all_dlbms, parcel_centroids)
        if centroid is None:
            centroid = boundary_center

        return centroid

    @staticmethod
    def _compute_parcel_centroids(
        landuse_geojson: Optional[Dict[str, Any]],
    ) -> Dict[str, Tuple[float, float]]:
        """Compute centroid coordinates for each DLBM group."""
        centroids: Dict[str, Tuple[float, float]] = {}

        if not landuse_geojson or not landuse_geojson.get("features"):
            return centroids

        try:
            import geopandas as gpd
            from shapely import from_geojson as shapely_from_geojson

            geoms = []
            dlbms = []
            for ft in landuse_geojson["features"]:
                g = ft.get("geometry", {})
                if g and g.get("coordinates"):
                    try:
                        geom = shapely_from_geojson(json.dumps(g))
                        if not geom.is_empty:
                            geoms.append(geom)
                            dlbms.append(str(ft.get("properties", {}).get("DLBM", "")).strip())
                    except Exception:
                        continue

            if not geoms:
                return centroids

            gdf = gpd.GeoDataFrame({"DLBM": dlbms}, geometry=geoms, crs="EPSG:4326")

            # Compute centroid per DLBM group
            for dlbm, group in gdf.groupby("DLBM"):
                center = group.geometry.union_all().centroid
                centroids[dlbm] = (center.x, center.y)

        except ImportError:
            # Fallback: simple average of feature coordinates
            for ft in landuse_geojson["features"]:
                props = ft.get("properties", {})
                dlbm = str(props.get("DLBM", "")).strip()
                g = ft.get("geometry", {})
                if g and g.get("type") == "Polygon" and g.get("coordinates"):
                    coords = g["coordinates"][0]
                    if coords:
                        avg_lon = sum(c[0] for c in coords) / len(coords)
                        avg_lat = sum(c[1] for c in coords) / len(coords)
                        centroids[dlbm] = (avg_lon, avg_lat)

        return centroids

    @staticmethod
    def _compute_boundary_center(
        boundary_geojson: Optional[Dict[str, Any]],
    ) -> Optional[List[float]]:
        """Compute boundary centroid as fallback placement point."""
        if not boundary_geojson or not boundary_geojson.get("features"):
            return None

        try:
            import geopandas as gpd
            from shapely import from_geojson as shapely_from_geojson

            geoms = []
            for ft in boundary_geojson["features"]:
                g = ft.get("geometry", {})
                if g and g.get("coordinates"):
                    geom = shapely_from_geojson(json.dumps(g))
                    if not geom.is_empty:
                        geoms.append(geom)

            if geoms:
                center = gpd.GeoSeries(geoms, crs="EPSG:4326").union_all().centroid
                return [center.x, center.y]
        except (ImportError, Exception):
            pass

        return None

    @staticmethod
    def _centroid_of_dlbm(
        dlbms: List[str],
        centroids: Dict[str, Tuple[float, float]],
    ) -> Optional[List[float]]:
        """Get centroid of the first available DLBM group."""
        for dlbm in dlbms:
            if dlbm in centroids:
                return list(centroids[dlbm])
        return None

    @staticmethod
    def _get_service_radius(fac_type: str, status: str) -> int:
        """Get service radius in meters based on facility type and status."""
        base_radius = {
            "村委会": 500,
            "学校": 800,
            "卫生站": 600,
            "文化站": 400,
            "市场": 1000,
            "养老服务": 400,
            "产业服务中心": 500,
            "停车场": 300,
        }
        radius = base_radius.get(fac_type, 500)
        if status in ("规划改扩建", "upgraded"):
            radius = int(radius * 1.5)
        return radius
