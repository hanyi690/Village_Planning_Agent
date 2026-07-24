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
from typing import Any, Dict, List, Optional

import yaml

from app.modules.schema.types.canonical import BBox
from app.utils.logger import get_logger

from ..contracts import DataResult, DataSourceMetadata
from ..sources import DataSourceDriver, DriverRegistry
from .config import CatalogConfig

logger = get_logger(__name__)

DEFAULT_CONFIG_PATH = Path(__file__).parent / "sources.yaml"


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

    def load_village_data(
        self,
        village_name: str,
        bbox: BBox,
        layer_types: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Load all relevant data for a village.

        Args:
            village_name: village name for metadata.
            bbox: village bounding box (WGS84).
            layer_types: specific layer types to load. If None, loads all
                configured sources that support bbox queries.

        Returns:
            Dict mapping gis_data keys to DataResult data.
        """
        if layer_types is None:
            layer_types = []
            for name, cfg in self._sources_cfg.items():
                if cfg.get("layer_type"):
                    layer_types.append(cfg["layer_type"])
                for layer in cfg.get("layers", []):
                    lt = layer.get("layer_type")
                    if lt and lt not in layer_types:
                        layer_types.append(lt)

        results = self.query_by_bbox(bbox, layer_types)

        gis_data: Dict[str, Any] = {}
        for lt, result in results.items():
            if result.success and result.data_type == "geojson":
                gis_data[f"{lt}_geojson"] = result.data
            elif not result.success:
                logger.warning("[DataCatalog] Failed to load %s: %s", lt, result.error)

        gis_data["_metadata"] = {
            "village_name": village_name,
            "bbox": bbox.as_tuple,
            "sources_loaded": list(gis_data.keys()),
        }
        return gis_data

    # layer_type -> (ingest port, ingest arg) mapping for typed bundle loading.
    # None means the layer is wrapped as a raw GeoFeature list (no typed model).
    _TYPED_LAYER_MAP: Dict[str, Optional[tuple]] = {
        "boundary": None,
        "landuse_current": ("result_to_parcels", "current_landuse"),
        "landuse_planned": ("result_to_parcels", "planned_landuse"),
        "annotation": ("result_to_features", "current_annotation"),
        "annotation_planned": ("result_to_features", "planned_annotation"),
        "road": ("result_to_features", "current_road"),
        "road_planned": ("result_to_features", "planned_road"),
        "admin_area": ("result_to_features", "admin_area"),
        "admin_boundary_line": ("result_to_features", "admin_boundary_line"),
        "farmland_protection": ("result_to_features", "farmland_protection"),
        "ecological_protection": ("result_to_features", "ecological_redline"),
        "ecological_redline": ("result_to_features", "ecological_redline"),
        "urban_dev_boundary": ("result_to_features", "urban_dev_boundary"),
        "village_dev_boundary": ("result_to_features", "village_dev_boundary"),
        "cultivated_land_target": ("result_to_features", "cultivated_land_target"),
        "historical_protection": ("result_to_features", "historical_protection"),
        "construction_zone": ("result_to_features", "conditional_construction"),
        "geological_hazard_points": ("result_to_features", "geological_hazard_pt"),
        "planning_scope": ("result_to_features", "planning_scope"),
        "land_use_zone": ("result_to_features", "land_use_zone"),
        "space_control_zone": ("result_to_features", "construction_ctrl_zone"),
        "water": ("result_to_features", "water_feature"),
    }

    def load_village_bundle(
        self,
        village_name: str,
        bbox: BBox,
        layer_types: Optional[List[str]] = None,
    ):
        """Load village data and return a typed ``GISDataBundle``.

        Unlike :meth:`load_village_data` (which returns raw GeoJSON dicts),
        this method runs every layer through the ingest port so downstream
        consumers (kg / parse / gis tools) receive typed schema models and
        never touch raw file data.

        Args:
            village_name: village name for metadata.
            bbox: village bounding box (WGS84).
            layer_types: specific layer types to load. If None, loads all
                configured sources whose layer_type is in ``_TYPED_LAYER_MAP``.

        Returns:
            ``GISDataBundle`` with boundary, landuse, roads, annotations and
            metadata populated from typed schema models.
        """
        from app.modules.schema import GISDataBundle, GISMetadata, GeoFeature
        from ..ingest import result_to_parcels, result_to_features

        if layer_types is None:
            layer_types = list(self._TYPED_LAYER_MAP.keys())

        results = self.query_by_bbox(bbox, layer_types)

        bundle = GISDataBundle(
            metadata=GISMetadata(
                village_name=village_name,
                bbox_wgs84=bbox,
                provider_sources=list(results.keys()),
            )
        )

        for lt, result in results.items():
            if not result.success:
                logger.warning("[DataCatalog] Skipping %s: %s", lt, result.error)
                continue
            mapping = self._TYPED_LAYER_MAP.get(lt)
            if mapping is None:
                # boundary / untyped layers -> wrap as GeoFeature list
                geojson = result.data if isinstance(result.data, dict) else None
                if geojson and geojson.get("type") == "FeatureCollection":
                    feats = [
                        GeoFeature(geometry=f.get("geometry", {}), properties=f.get("properties", {}))
                        for f in geojson.get("features", [])
                    ]
                    self._assign_to_bundle(bundle, lt, feats)
                continue

            port_name, arg = mapping
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
        logger.info(
            "[DataCatalog] load_village_bundle('%s'): %d parcels, %d roads, %d annotations",
            village_name, len(bundle.landuse), len(bundle.roads), len(bundle.annotations),
        )
        return bundle

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
