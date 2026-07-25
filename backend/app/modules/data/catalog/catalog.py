"""Data catalog - unified entry point for all data sources.

Loads YAML configuration, initializes drivers via DriverRegistry, and
provides query methods for spatial data retrieval.

Usage:
    from app.modules.data import DataCatalog

    catalog = DataCatalog()
    result = catalog.get_source("jintian_current_landuse").fetch()

Phase 1: skeleton with config loading and source initialization.
Connection instantiation (Phase 2) and concrete drivers (Phase 3) are
wired in later phases. Until then, sources whose driver is not yet
registered are skipped with a warning.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

from app.modules.schema.types.canonical import BBox, VillageBundle, VillageMetadata
from app.modules.schema.types.base import PointFeature as _PointFeature, LineFeature as _LineFeature, PolygonFeature as _PolygonFeature
from app.modules.schema.types.spatial_types import (
    AdminArea as _AdminArea, AdminBoundaryLine as _AdminBoundaryLine,
    ConditionalConstructionZone as _ConditionalConstructionZone,
    ConstructionCtrlZone as _ConstructionCtrlZone,
    ContourLine as _ContourLine,
    CultivatedLandTarget as _CultivatedLandTarget,
    CurrentAnnotation as _CurrentAnnotation, PlannedAnnotation as _PlannedAnnotation,
    CurrentBuilding as _CurrentBuilding,
    CurrentFacility as _CurrentFacility, PlannedFacility as _PlannedFacility,
    CurrentLandUseParcel as _CurrentLandUseParcel,
    PlannedLandUseParcel as _PlannedLandUseParcel,
    CurrentRoad as _CurrentRoad, PlannedRoad as _PlannedRoad,
    EcologicalRedline as _EcologicalRedline,
    ElevationPoint as _ElevationPoint,
    FarmlandProtection as _FarmlandProtection,
    FloodControlLine as _FloodControlLine,
    GeologicalHazardPoint as _GeologicalHazardPoint,
    HazardControlLine as _HazardControlLine,
    HistoricalProtection as _HistoricalProtection,
    HydrogeologyZone as _HydrogeologyZone,
    LandUseZone as _LandUseZone,
    NatureReserve as _NatureReserve,
    PlanningScope as _PlanningScope,
    SoilErosion as _SoilErosion,
    SoilType as _SoilType,
    ThreeZoneItem as _ThreeZoneItem,
    UrbanDevBoundary as _UrbanDevBoundary,
    VillageDevBoundary as _VillageDevBoundary,
    WaterFeature as _WaterFeature,
    Watershed as _Watershed,
)
from app.utils.logger import get_logger

from ..contracts import DataResult, DataSourceMetadata
from ..sources import DataSourceDriver, DriverRegistry
from .config import CatalogConfig

logger = get_logger(__name__)

DEFAULT_CONFIG_PATH = Path(__file__).parent / "sources.yaml"


def _extract_coords(geometry: Dict[str, Any], out: List[Tuple[float, float]]) -> None:
    """Recursively extract (lon, lat) coordinate pairs from a GeoJSON geometry."""
    geom_type = geometry.get("type", "")
    coords = geometry.get("coordinates", [])

    if geom_type == "Point":
        if len(coords) >= 2:
            out.append((coords[0], coords[1]))
    elif geom_type in ("LineString", "MultiPoint"):
        for c in coords:
            if len(c) >= 2:
                out.append((c[0], c[1]))
    elif geom_type in ("Polygon", "MultiLineString"):
        for ring in coords:
            for c in ring:
                if len(c) >= 2:
                    out.append((c[0], c[1]))
    elif geom_type == "MultiPolygon":
        for polygon in coords:
            for ring in polygon:
                for c in ring:
                    if len(c) >= 2:
                        out.append((c[0], c[1]))


class DataCatalog:
    """Data catalog - manages all configured data sources.

    Lifecycle:
        1. Load YAML configuration (sources + connections)
        2. Register connections (Phase 2)
        3. Instantiate drivers via DriverRegistry
        4. Query sources by name or layer_type
    """

    def __init__(self, config_path: Optional[str] = None):
        self.config_path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
        self._raw: Dict[str, Any] = {}
        self._connections: Dict[str, Dict[str, Any]] = {}
        self._sources_cfg: Dict[str, Dict[str, Any]] = {}
        self._sources: Dict[str, DataSourceDriver] = {}
        self._load_config()
        self._init_connections()
        self._init_sources()

    # ── configuration loading ──

    def _load_config(self) -> None:
        if not self.config_path.exists():
            logger.warning(
                "[DataCatalog] Config not found: %s. Using empty catalog.",
                self.config_path,
            )
            self._raw = {"version": "1.0", "sources": {}, "connections": {}}
            return

        with open(self.config_path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}

        try:
            catalog = CatalogConfig(**raw)
            self._raw = raw
            self._connections = catalog.connections
            self._sources_cfg = catalog.sources
            logger.info(
                "[DataCatalog] Loaded %d sources, %d connections from %s",
                len(self._sources_cfg),
                len(self._connections),
                self.config_path,
            )
        except Exception as e:
            logger.error("[DataCatalog] Config validation failed: %s", e)
            raise

    # ── connection initialization (Phase 2 stub) ──

    def _init_connections(self) -> None:
        """Instantiate and register connections from YAML declarations."""
        from ..connections import ConnectionRegistry
        from ..connections.amap import AmapConnection
        from ..connections.gd_tianditu import GDTiandituConnection
        from ..connections.osm import OSMConnection
        from ..connections.tianditu import TiandituConnection

        _classes = {
            "tianditu": TiandituConnection,
            "amap": AmapConnection,
            "gd_tianditu": GDTiandituConnection,
            "osm": OSMConnection,
        }

        for name, cfg in self._connections.items():
            conn_cls = _classes.get(cfg.type)
            if conn_cls is None:
                logger.warning(
                    "[DataCatalog] Unknown connection type '%s' for '%s'. Skipping.",
                    cfg.type,
                    name,
                )
                continue
            try:
                conn = conn_cls()
                ConnectionRegistry.register(conn)
            except Exception as e:
                logger.error(
                    "[DataCatalog] Failed to init connection '%s': %s",
                    name,
                    e,
                )

    # ── source initialization ──

    def _init_sources(self) -> None:
        from app.core.settings import PROJECT_ROOT

        for name, cfg in self._sources_cfg.items():
            driver_name = cfg.get("driver", "")
            if not DriverRegistry.has_driver(driver_name):
                logger.warning(
                    "[DataCatalog] Driver '%s' not registered for source '%s'. "
                    "Skipping (will be available after Phase 3 migration).",
                    driver_name,
                    name,
                )
                continue

            try:
                driver_cls = DriverRegistry.get(driver_name)
                resolved_cfg = self._resolve_paths(cfg, PROJECT_ROOT)
                self._sources[name] = driver_cls(resolved_cfg)
                logger.info(
                    "[DataCatalog] Initialized source: %s (driver=%s)",
                    name,
                    driver_name,
                )
            except Exception as e:
                logger.error(
                    "[DataCatalog] Failed to init source '%s': %s",
                    name,
                    e,
                )

    @staticmethod
    def _resolve_paths(cfg: Dict[str, Any], project_root: Path) -> Dict[str, Any]:
        """Resolve relative paths in config against project root."""
        resolved = dict(cfg)
        for key in ("path", "cache_dir", "local_path"):
            if key in resolved:
                p = Path(resolved[key])
                if not p.is_absolute():
                    resolved[key] = str(project_root / p)
        return resolved

    # ── query API ──

    def get_source(self, name: str) -> DataSourceDriver:
        """Get a data source by name.

        Raises:
            KeyError: if source name is not found.
        """
        if name not in self._sources:
            available = list(self._sources.keys())
            raise KeyError(f"Unknown source: {name}. Available: {available}")
        return self._sources[name]

    def list_sources(self) -> List[str]:
        """Return all initialized source names."""
        return list(self._sources.keys())

    def find_source_by_layer_type(self, layer_type: str) -> Optional[DataSourceDriver]:
        """Find the first source supporting a given layer_type."""
        for name, source in self._sources.items():
            cfg = self._sources_cfg.get(name, {})
            if cfg.get("layer_type") == layer_type:
                return source
            for layer in cfg.get("layers", []):
                if layer.get("layer_type") == layer_type:
                    return source
        return None

    def query_by_bbox(
        self,
        bbox: BBox,
        layer_types: List[str],
    ) -> Dict[str, DataResult]:
        """Query multiple layer types by bounding box.

        Returns:
            Dict mapping layer_type to DataResult.
        """
        results: Dict[str, DataResult] = {}
        for lt in layer_types:
            source = self.find_source_by_layer_type(lt)
            if source is None:
                results[lt] = DataResult.fail(
                    error=f"No source configured for layer_type: {lt}"
                )
                continue
            try:
                results[lt] = source.fetch(bbox=bbox, layer_type=lt)
            except Exception as e:
                logger.error("[DataCatalog] Query failed for %s: %s", lt, e)
                results[lt] = DataResult.fail(error=str(e))
        return results

    # layer_type -> (ingest port, ingest arg) mapping for typed bundle loading.
    # Derived from LAYER_TYPE_REGISTRY (T6). Kept as backward compat property.
    @classmethod
    @property
    def _TYPED_LAYER_MAP(cls):
        """Backward compat -- derived from LAYER_TYPE_REGISTRY."""
        from app.modules.schema.types.layer_registry import LAYER_TYPE_REGISTRY
        return {
            lt: (e.ingest_port, e.ingest_arg) if e.ingest_port else None
            for lt, e in LAYER_TYPE_REGISTRY.items()
        }

    def load_village_bundle(
        self,
        village_name: str,
        layer_types: Optional[List[str]] = None,
    ):
        """Load village data bundle — morphology-first, no bbox required.

        Flow:
          1. Load boundary first (file_vector ignores bbox)
          2. Derive bbox from boundary geometry
          3. Fallback: geocode village_name if no boundary
          4. Load all layers (file_vector ignores bbox, api_vector uses it)
          5. Return typed VillageBundle with morphology groups populated

        Args:
            village_name: village name for metadata and geocode fallback.
            layer_types: specific layer types to load. If None, loads all
                configured sources whose layer_type is in ``LAYER_TYPE_REGISTRY``.

        Returns:
            ``VillageBundle`` with points/lines/polygons/rasters morphology groups.
        """
        from app.modules.schema.types.layer_registry import LAYER_TYPE_REGISTRY
        from ..ingest import result_to_parcels, result_to_features

        if layer_types is None:
            layer_types = list(LAYER_TYPE_REGISTRY.keys())

        # Step 1: Load boundary first (no bbox needed for file_vector)
        bbox = None
        bundle = VillageBundle(village_name=village_name)

        boundary_result = self._load_boundary(village_name)
        if boundary_result and boundary_result.success:
            # Step 2: Derive bbox from boundary geometry
            bbox = self._derive_bbox_from_boundary(boundary_result.data)
            # Assign boundary: ingest as AdminArea via result_to_features
            from ..ingest import result_to_features
            admin_features, _ = result_to_features(boundary_result, "admin_area")
            if admin_features:
                bundle.polygons.admin_areas.extend(admin_features)

        # Step 2b: Fallback — geocode if no boundary
        if bbox is None:
            bbox = self._geocode_village(village_name)

        # Step 3: Load all layers via query_by_bbox (file_vector ignores bbox)
        results = self.query_by_bbox(bbox, layer_types) if bbox else {}

        # Step 4: Build typed bundle from results
        for lt, result in results.items():
            if not result.success:
                logger.warning("[DataCatalog] Skipping %s: %s", lt, result.error)
                continue
            if lt == "boundary":
                # Already loaded in Step 1
                continue
            entry = LAYER_TYPE_REGISTRY.get(lt)
            if entry is None or entry.ingest_port is None:
                # Untyped layers — skip with warning (inference pipeline not yet active)
                logger.debug(
                    "[DataCatalog] Layer '%s' has no ingest port — skipping "
                    "(inference pipeline not yet active)", lt,
                )
                continue

            port_name, arg = entry.ingest_port, entry.ingest_arg
            if port_name == "result_to_parcels":
                parcels, warnings = result_to_parcels(result, layer_type=arg)
                if warnings:
                    bundle.metadata.crs_warnings.extend(warnings[:5])
                # _assign_to_bundle uses isinstance, so parcels will route correctly
                self._assign_to_bundle(bundle, parcels)
            elif port_name == "result_to_features":
                features, _warnings = result_to_features(result, arg)
                self._assign_to_bundle(bundle, features)
            elif port_name == "result_to_raster":
                from ..ingest import result_to_raster
                raster = result_to_raster(result, arg)
                if raster is not None:
                    if lt == "dem":
                        bundle.rasters.dem = raster
                    elif lt == "dom":
                        bundle.rasters.dom = raster

        bundle.metadata.provider_sources = list(results.keys())
        if bbox:
            bundle.metadata.bbox_wgs84 = bbox

        logger.info(
            "[DataCatalog] load_village_bundle('%s'): %d parcels, %d roads, %d annotations",
            village_name,
            bundle.parcel_count,
            len(bundle.lines.roads_current) + len(bundle.lines.roads_planned),
            len(bundle.points.annotations_current) + len(bundle.points.annotations_planned),
        )
        return bundle

    # ── Boundary-first helpers ──

    def _load_boundary(self, village_name: str) -> Optional[DataResult]:
        """Load boundary layer first (no bbox needed for file_vector)."""
        source = self.find_source_by_layer_type("boundary")
        if source is None:
            logger.debug("[DataCatalog] No boundary source configured")
            return None
        try:
            return source.fetch()  # file_vector ignores bbox
        except Exception as e:
            logger.warning("[DataCatalog] Boundary load failed: %s", e)
            return None

    @staticmethod
    def _derive_bbox_from_boundary(geojson: Dict[str, Any]) -> Optional[BBox]:
        """Derive BBox from boundary GeoJSON geometry.

        Extracts all coordinates from the boundary features and computes
        the axis-aligned bounding box. Returns None if no valid coordinates.
        """
        if not isinstance(geojson, dict):
            return None
        features = geojson.get("features", [])
        if not features:
            return None

        all_coords: List[Tuple[float, float]] = []
        for f in features:
            geom = f.get("geometry", {})
            _extract_coords(geom, all_coords)

        if not all_coords:
            return None

        lons = [c[0] for c in all_coords]
        lats = [c[1] for c in all_coords]
        bbox = BBox(west=min(lons), south=min(lats), east=max(lons), north=max(lats))
        if bbox.is_valid():
            return bbox
        return None

    def _geocode_village(self, village_name: str) -> Optional[BBox]:
        """Fallback: geocode village name to bbox (when no boundary data).

        Tries Tianditu geocode first, then POI search in the county region.
        Returns a 5km buffer bbox around the located point, or None.
        """
        from ..connections import ConnectionRegistry

        conn = ConnectionRegistry.get("tianditu")
        if conn is None:
            logger.debug("[DataCatalog] No tianditu connection for geocode fallback")
            return None

        # Step 1: Direct geocode
        result = conn.geocode(village_name)
        if result.success and result.lon != 0:
            center = (result.lon, result.lat)
            logger.info("[DataCatalog] geocode: %s -> (%.4f, %.4f)", village_name, *center)
            return self._center_to_bbox(center, 5.0)

        # Step 2: POI search in county region
        from app.utils.location_parser import parse_location_hierarchy
        try:
            hierarchy = parse_location_hierarchy(village_name)
            county = hierarchy.get("county", "")
            if county:
                poi_result = conn.search_poi_in_region(village_name, county)
                if poi_result.success and poi_result.pois:
                    first = poi_result.pois[0]
                    center = (first.get("lon", 0), first.get("lat", 0))
                    if center[0] != 0:
                        logger.info(
                            "[DataCatalog] POI: %s -> (%.4f, %.4f)",
                            village_name, *center,
                        )
                        return self._center_to_bbox(center, 5.0)
        except Exception as e:
            logger.warning("[DataCatalog] POI fallback failed: %s", e)

        logger.warning("[DataCatalog] Could not locate %s via geocode", village_name)
        return None

    @staticmethod
    def _center_to_bbox(
        center: Tuple[float, float], buffer_km: float
    ) -> BBox:
        """Convert a center point + buffer distance to a BBox."""
        buffer_deg = buffer_km / 111.0
        return BBox(
            west=center[0] - buffer_deg,
            south=center[1] - buffer_deg,
            east=center[0] + buffer_deg,
            north=center[1] + buffer_deg,
        )

    @staticmethod
    def _assign_to_bundle(bundle, features: List[Any]) -> None:
        """Route typed SpatialFeature instances to the correct morphology group.

        [v4.3] Uses isinstance dispatch instead of string-based layer_type matching.
        Each of the 33 concrete SpatialFeature subclasses has a deterministic home
        in one of the morphology groups. Inferred/unknown types fall through to the
        base-class catch-all (PointFeature/LineFeature/PolygonFeature inferred lists).
        """
        for feat in features:
            # ── PolygonFeature subclasses ──
            if isinstance(feat, _CurrentLandUseParcel):
                bundle.polygons.landuse_current.append(feat)
            elif isinstance(feat, _PlannedLandUseParcel):
                bundle.polygons.landuse_planned.append(feat)
            elif isinstance(feat, _FarmlandProtection):
                bundle.polygons.farmland_protection.append(feat)
            elif isinstance(feat, _EcologicalRedline):
                bundle.polygons.ecological_redline.append(feat)
            elif isinstance(feat, _HistoricalProtection):
                bundle.polygons.historical_protection.append(feat)
            elif isinstance(feat, _CultivatedLandTarget):
                bundle.polygons.cultivated_land_target.append(feat)
            elif isinstance(feat, _UrbanDevBoundary):
                bundle.polygons.urban_dev_boundary.append(feat)
            elif isinstance(feat, _VillageDevBoundary):
                bundle.polygons.village_dev_boundary.append(feat)
            elif isinstance(feat, _HazardControlLine):
                bundle.polygons.hazard_control_lines.append(feat)
            elif isinstance(feat, _FloodControlLine):
                bundle.polygons.flood_control_lines.append(feat)
            elif isinstance(feat, _ConditionalConstructionZone):
                bundle.polygons.construction_zone.append(feat)
            elif isinstance(feat, _AdminArea):
                bundle.polygons.admin_areas.append(feat)
            elif isinstance(feat, _PlanningScope):
                bundle.polygons.planning_scope.append(feat)
            elif isinstance(feat, _LandUseZone):
                bundle.polygons.land_use_zones.append(feat)
            elif isinstance(feat, _ConstructionCtrlZone):
                bundle.polygons.construction_ctrl_zones.append(feat)
            elif isinstance(feat, _ThreeZoneItem):
                bundle.polygons.three_zones.append(feat)
            elif isinstance(feat, _WaterFeature):
                bundle.polygons.water_bodies.append(feat)
            elif isinstance(feat, _SoilType):
                bundle.polygons.soil_types.append(feat)
            elif isinstance(feat, _SoilErosion):
                bundle.polygons.soil_erosions.append(feat)
            elif isinstance(feat, _Watershed):
                bundle.polygons.watersheds.append(feat)
            elif isinstance(feat, _NatureReserve):
                bundle.polygons.nature_reserves.append(feat)
            elif isinstance(feat, _HydrogeologyZone):
                bundle.polygons.hydrogeology_zones.append(feat)

            # ── LineFeature subclasses ──
            elif isinstance(feat, _CurrentRoad):
                bundle.lines.roads_current.append(feat)
            elif isinstance(feat, _PlannedRoad):
                bundle.lines.roads_planned.append(feat)
            elif isinstance(feat, _ContourLine):
                bundle.lines.contour_lines.append(feat)
            elif isinstance(feat, _AdminBoundaryLine):
                bundle.lines.admin_boundaries.append(feat)

            # ── PointFeature subclasses ──
            elif isinstance(feat, _CurrentFacility):
                bundle.points.facilities_current.append(feat)
            elif isinstance(feat, _PlannedFacility):
                bundle.points.facilities_planned.append(feat)
            elif isinstance(feat, _CurrentBuilding):
                bundle.points.buildings.append(feat)
            elif isinstance(feat, _ElevationPoint):
                bundle.points.elevation_points.append(feat)
            elif isinstance(feat, _GeologicalHazardPoint):
                bundle.points.hazard_points.append(feat)
            elif isinstance(feat, _CurrentAnnotation):
                bundle.points.annotations_current.append(feat)
            elif isinstance(feat, _PlannedAnnotation):
                bundle.points.annotations_planned.append(feat)

            # ── Inferred fallback (base classes) ──
            elif isinstance(feat, _PolygonFeature):
                bundle.polygons.inferred.append(feat)
            elif isinstance(feat, _LineFeature):
                bundle.lines.inferred.append(feat)
            elif isinstance(feat, _PointFeature):
                bundle.points.inferred.append(feat)


__all__ = ["DataCatalog"]
