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

from app.modules.schema.types.canonical import BBox
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


def _bundle_to_compat_dict(bundle: Any) -> Dict[str, Any]:
    """Convert GISDataBundle to raw dict for compute_spatial_context compat.

    During the transition period, compute_spatial_context still reads
    raw GeoJSON dicts keyed by ``{layer_type}_geojson``. This helper
    bridges the typed bundle to that format.

    TODO: Remove after T3 migration completes and all consumers accept bundles.
    """
    from app.modules.schema.types.canonical import GeoFeature

    gis_data: Dict[str, Any] = {}

    # Boundary
    if bundle.boundary is not None:
        feat = _geofeature_to_geojson(bundle.boundary)
        gis_data["boundary_geojson"] = {
            "type": "FeatureCollection",
            "features": [feat],
        }

    # Landuse parcels -> FeatureCollection
    if bundle.landuse:
        features = []
        for p in bundle.landuse:
            if isinstance(p, GeoFeature):
                features.append(_geofeature_to_geojson(p))
            elif isinstance(p, dict):
                features.append(p)
            elif hasattr(p, "geometry") and isinstance(getattr(p, "geometry", None), dict):
                # Dataclass-style parcel (CurrentLandUseParcel, etc.)
                geom = p.geometry
                props = {k: v for k, v in p.__dict__.items() if k != "geometry" and not k.startswith("_")}
                features.append({"type": "Feature", "geometry": geom, "properties": props})
            elif hasattr(p, "model_dump"):
                d = p.model_dump()
                geom = d.get("geometry", {})
                props = {k: v for k, v in d.items() if k != "geometry"}
                features.append({"type": "Feature", "geometry": geom, "properties": props})
        gis_data["landuse_current_geojson"] = {
            "type": "FeatureCollection",
            "features": features,
        }

    # Roads
    if bundle.roads:
        gis_data["road_geojson"] = _geofeatures_to_fc(bundle.roads)

    # Water bodies
    if bundle.water_bodies:
        gis_data["water_geojson"] = _geofeatures_to_fc(bundle.water_bodies)

    # Annotations
    if bundle.annotations:
        gis_data["annotation_geojson"] = _geofeatures_to_fc(bundle.annotations)

    # Metadata
    gis_data["_metadata"] = {
        "village_name": bundle.metadata.village_name,
        "bbox": bundle.metadata.bbox_wgs84.as_tuple if bundle.metadata.bbox_wgs84 else None,
    }

    return gis_data


def _geofeature_to_geojson(feat: Any) -> Dict[str, Any]:
    """Convert a GeoFeature, dataclass parcel, or dict to a GeoJSON Feature dict."""
    from app.modules.schema.types.canonical import GeoFeature

    if isinstance(feat, dict):
        return feat
    # Pydantic GeoFeature
    if isinstance(feat, GeoFeature):
        return {
            "type": "Feature",
            "geometry": feat.geometry if isinstance(feat.geometry, dict) else {},
            "properties": feat.properties if isinstance(feat.properties, dict) else {},
        }
    # Dataclass-style spatial feature (CurrentLandUseParcel, CurrentAnnotation, etc.)
    if hasattr(feat, "geometry") and isinstance(getattr(feat, "geometry", None), dict):
        geom = feat.geometry
        props = {k: v for k, v in feat.__dict__.items() if k != "geometry" and not k.startswith("_")}
        # Map typed fields back to GeoJSON property names for compat
        if "text" in props and "注记" not in props:
            props["注记"] = props.pop("text")
        if "category" in props and "分类" not in props:
            props["分类"] = props.pop("category")
        return {"type": "Feature", "geometry": geom, "properties": props}
    # Pydantic model fallback
    if hasattr(feat, "model_dump"):
        return feat.model_dump()
    return {"type": "Feature", "geometry": {}, "properties": {}}


def _geofeatures_to_fc(features: List[Any]) -> Dict[str, Any]:
    """Convert a list of GeoFeature to a FeatureCollection dict."""
    return {
        "type": "FeatureCollection",
        "features": [_geofeature_to_geojson(f) for f in features],
    }


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
        """Load village data bundle — schema-driven, no bbox required.

        Flow:
          1. Load boundary first (file_vector ignores bbox)
          2. Derive bbox from boundary geometry
          3. Fallback: geocode village_name if no boundary
          4. Load all layers (file_vector ignores bbox, api_vector uses it)
          5. Return typed GISDataBundle

        Args:
            village_name: village name for metadata and geocode fallback.
            layer_types: specific layer types to load. If None, loads all
                configured sources whose layer_type is in ``LAYER_TYPE_REGISTRY``.

        Returns:
            ``GISDataBundle`` with boundary, landuse, roads, annotations and
            metadata populated from typed schema models.
        """
        from app.modules.schema import GISDataBundle, GISMetadata, GeoFeature
        from app.modules.schema.types.layer_registry import LAYER_TYPE_REGISTRY
        from ..ingest import result_to_parcels, result_to_features

        if layer_types is None:
            layer_types = list(LAYER_TYPE_REGISTRY.keys())

        # Step 1: Load boundary first (no bbox needed for file_vector)
        bbox = None
        bundle = GISDataBundle(metadata=GISMetadata(village_name=village_name))

        boundary_result = self._load_boundary(village_name)
        if boundary_result and boundary_result.success:
            # Step 2: Derive bbox from boundary geometry
            bbox = self._derive_bbox_from_boundary(boundary_result.data)
            # Assign boundary to bundle
            geojson = boundary_result.data
            if geojson and isinstance(geojson, dict) and geojson.get("type") == "FeatureCollection":
                feats = [
                    GeoFeature(
                        geometry=f.get("geometry", {}),
                        properties=f.get("properties", {}),
                    )
                    for f in geojson.get("features", [])
                ]
                if feats:
                    bundle.boundary = feats[0]

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
                # Untyped layers -> wrap as GeoFeature list
                geojson = result.data if isinstance(result.data, dict) else None
                if geojson and geojson.get("type") == "FeatureCollection":
                    feats = [
                        GeoFeature(
                            geometry=f.get("geometry", {}),
                            properties=f.get("properties", {}),
                        )
                        for f in geojson.get("features", [])
                    ]
                    self._assign_to_bundle(bundle, lt, feats)
                continue

            port_name, arg = entry.ingest_port, entry.ingest_arg
            if port_name == "result_to_parcels":
                parcels, warnings = result_to_parcels(result, layer_type=arg)
                if warnings:
                    bundle.metadata.crs_warnings.extend(warnings[:5])
                if lt == "landuse_current":
                    bundle.landuse = parcels
                else:
                    bundle.landuse.extend(parcels)
            elif port_name == "result_to_features":
                features, _warnings = result_to_features(result, arg)
                self._assign_to_bundle(bundle, lt, features)

        bundle.metadata.parcel_count = len(bundle.landuse)
        bundle.metadata.provider_sources = list(results.keys())
        if bbox:
            bundle.metadata.bbox_wgs84 = bbox

        logger.info(
            "[DataCatalog] load_village_bundle('%s'): %d parcels, %d roads, %d annotations",
            village_name, len(bundle.landuse), len(bundle.roads), len(bundle.annotations),
        )
        return bundle

    def load_village_bundle_with_raw(
        self,
        village_name: str,
        layer_types: Optional[List[str]] = None,
    ):
        """Load village bundle and also return raw GeoJSON dict for compat.

        Returns (GISDataBundle, Dict[str, Any]) where the dict contains
        raw GeoJSON keyed by ``{layer_type}_geojson`` for
        ``compute_spatial_context`` compatibility during transition.

        The raw dict includes protection zone layers that are not yet
        represented in GISDataBundle fields.
        """
        from app.modules.schema.types.layer_registry import LAYER_TYPE_REGISTRY

        bundle = self.load_village_bundle(village_name, layer_types=layer_types)
        raw = _bundle_to_compat_dict(bundle)

        # Add protection zone layers from query results (not in bundle fields)
        # These are needed by compute_spatial_context and KG builder
        protection_types = [
            "farmland_protection", "ecological_protection",
            "historical_protection", "construction_zone",
            "geological_hazard",
        ]
        for lt in protection_types:
            source = self.find_source_by_layer_type(lt)
            if source is None:
                continue
            try:
                result = source.fetch()  # file_vector ignores bbox
                if result.success and result.data_type == "geojson":
                    raw[f"{lt}_geojson"] = result.data
                elif result.success and isinstance(result.data, dict):
                    raw[f"{lt}_geojson"] = result.data
            except Exception as e:
                logger.debug("[DataCatalog] Protection zone %s load skipped: %s", lt, e)

        return bundle, raw

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
        from app.modules.data.fetcher import GISDataFetcher
        try:
            hierarchy = GISDataFetcher().parse_location_hierarchy(village_name)
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
    def _assign_to_bundle(bundle, layer_type: str, features: List[Any]) -> None:
        """Route typed features to the correct GISDataBundle field."""
        if layer_type in ("boundary", "admin_area", "planning_scope") and features:
            if bundle.boundary is None:
                bundle.boundary = features[0]
        elif layer_type in ("road", "road_planned"):
            bundle.roads.extend(features)
        elif layer_type in ("annotation", "annotation_planned"):
            bundle.annotations.extend(features)
        elif layer_type in ("water",):
            bundle.water_bodies.extend(features)


__all__ = ["DataCatalog"]
